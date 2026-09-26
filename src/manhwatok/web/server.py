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
from manhwatok.domain.text import plain_title
from manhwatok.web import events
from manhwatok.web.jobs import EventBus, JobRunner
from manhwatok.web.drafts import ArtLists, Drafts
from manhwatok.web.routes import edit, files, header, new, posts

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
    app.state.drafts = Drafts()
    app.state.art_lists = ArtLists()
    app.state.templates = Jinja2Templates(directory=HERE / "templates")
    # Titles carry *accent* marks for the slides; pages show them plain, as the TUI does.
    app.state.templates.env.filters["plain"] = plain_title

    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    hosts = {origin.split("//", 1)[1] for origin in origins}
    app.state.origins = origins

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
        response = await call_next(request)
        # No other site may frame it and lure clicks onto its buttons (clickjacking).
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        return response

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    # The slides' own font, so the pages and the slides read as one thing.
    fonts = HERE.parent / "assets" / "fonts"
    app.mount("/fonts", StaticFiles(directory=fonts), name="fonts")
    app.include_router(events.router)
    app.include_router(header.router)
    app.include_router(edit.router)
    app.include_router(posts.router)
    app.include_router(files.router)
    app.include_router(new.router)

    @app.get("/")
    def home() -> RedirectResponse:
        return RedirectResponse("/posts", status_code=303)

    return app


def stop_streams_on_exit(server, stop: threading.Event) -> None:
    """End the tabs' event streams as soon as Ctrl-C arrives. Uvicorn waits for open requests
    before the app's own shutdown runs, and an event stream never ends by itself."""
    handle_exit = server.handle_exit

    def exiting(sig, frame) -> None:
        stop.set()
        handle_exit(sig, frame)

    server.handle_exit = exiting


def run(settings: Settings, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    """Serve the app on 127.0.0.1:`port` until Ctrl-C, which ends the tabs' event streams at
    once so it doesn't wait on them (anything else still open gets two seconds)."""
    import uvicorn

    ctx = open_context(settings)
    try:
        app = create_app(ctx, port=port)
        url = f"http://127.0.0.1:{port}/"
        if open_browser:
            threading.Timer(1.0, webbrowser.open, (url,)).start()
        print(f"manhwatok web on {url} — Ctrl-C stops it")
        server = uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=2
            )
        )
        stop_streams_on_exit(server, app.state.stop)
        server.run()
    finally:
        ctx.close()
