"""The manhwatok web app: FastAPI on 127.0.0.1, pages rendered on the server, htmx in the page.

It can publish to TikTok, so it only answers this computer: requests must be addressed to
127.0.0.1/localhost on its port (no DNS rebinding), and anything that changes something must come
from its own pages (no other website open in the same browser can post to it)."""

from __future__ import annotations

import threading
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from manhwatok.app.context import AppContext, open_context
from manhwatok.config import Settings
from manhwatok.web import events
from manhwatok.web.jobs import EventBus, JobRunner
from manhwatok.web.routes import files, header, posts

HERE = Path(__file__).parent
DEFAULT_PORT = 8421
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else None


def create_app(
    ctx: AppContext,
    *,
    port: int = DEFAULT_PORT,
    clock: Callable[[], datetime] = _utc_now,
    watch_interval: float | None = 2.0,
) -> FastAPI:
    """The app around an open `ctx` (the caller closes it). `watch_interval`: how often to look
    for changes made elsewhere (CLI, TUI); None never looks (tests)."""
    bus = EventBus()
    jobs = JobRunner(bus)
    stop = threading.Event()
    watcher = (
        events.ChangeWatcher(bus, events.change_probes(ctx), watch_interval)
        if watch_interval
        else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if watcher is not None:
            watcher.start()
        yield
        stop.set()  # event streams end
        jobs.stop()  # questions answered no, no new jobs
        if watcher is not None:
            watcher.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx
    app.state.bus = bus
    app.state.jobs = jobs
    app.state.stop = stop
    app.state.clock = clock
    app.state.templates = Jinja2Templates(directory=HERE / "templates")

    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    hosts = {origin.split("//", 1)[1] for origin in origins}

    @app.middleware("http")
    async def only_this_computer(request: Request, call_next):
        if request.headers.get("host") not in hosts:
            return PlainTextResponse("this app only answers 127.0.0.1", status_code=403)
        if request.method in UNSAFE:
            origin = request.headers.get("origin") or _origin_of(
                request.headers.get("referer", "")
            )
            if origin not in origins:
                return PlainTextResponse("not from this app's pages", status_code=403)
        return await call_next(request)

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.include_router(events.router)
    app.include_router(header.router)
    app.include_router(posts.router)
    app.include_router(files.router)

    @app.get("/")
    def home() -> RedirectResponse:
        return RedirectResponse("/posts", status_code=303)

    return app


def run(settings: Settings, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    """Serve the app on 127.0.0.1:`port` until Ctrl-C. Open event streams are cut after two
    seconds on the way out, so Ctrl-C doesn't wait on the tabs."""
    import uvicorn

    ctx = open_context(settings)
    try:
        app = create_app(ctx, port=port)
        url = f"http://127.0.0.1:{port}/"
        if open_browser:
            threading.Timer(1.0, webbrowser.open, (url,)).start()
        print(f"manhwatok web on {url} — Ctrl-C stops it")
        uvicorn.run(
            app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=2
        )
    finally:
        ctx.close()
