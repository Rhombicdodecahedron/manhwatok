"""Live updates: one Server-Sent Events stream per tab, carrying what the event bus publishes,
and a watcher that notices changes made elsewhere (the CLI, the TUI) and publishes them too."""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from manhwatok.app.context import AppContext
from manhwatok.web.jobs import EventBus

router = APIRouter()


def sse_stream(bus: EventBus, stop: threading.Event, heartbeat: float = 15.0) -> Iterator[str]:
    """The stream's lines: events as they come, a ping after `heartbeat` quiet seconds (so a
    dead tab is noticed), and the end within a second of `stop`."""
    q = bus.subscribe()
    try:
        yield "retry: 2000\n\n"
        quiet_since = time.monotonic()
        while not stop.is_set():
            try:
                kind, data = q.get(timeout=min(1.0, heartbeat))
            except queue.Empty:
                if time.monotonic() - quiet_since >= heartbeat:
                    quiet_since = time.monotonic()
                    yield ": ping\n\n"
                continue
            quiet_since = time.monotonic()
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"
    finally:
        bus.unsubscribe(q)


@router.get("/events")
def events(request: Request) -> StreamingResponse:
    state = request.app.state
    return StreamingResponse(
        sse_stream(state.bus, state.stop),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )


class ChangeWatcher:
    """Looks at each probe every `interval` seconds and publishes ("changed", {"what": name})
    when its value differs from the last look. A probe raising OSError reads as None."""

    def __init__(
        self, bus: EventBus, probes: dict[str, Callable[[], object]], interval: float
    ) -> None:
        self._bus, self._probes, self._interval = bus, probes, interval
        self._last: dict[str, object] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check(self) -> list[str]:
        changed = []
        for name, probe in self._probes.items():
            try:
                value = probe()
            except OSError:
                value = None
            if name in self._last and self._last[name] != value:
                changed.append(name)
            self._last[name] = value
        for name in changed:
            self._bus.publish("changed", what=name)
        return changed

    def start(self) -> None:
        self.check()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="change-watcher")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.check()


def _mtimes(db: Path) -> tuple:
    """The database and its write-ahead log: SQLite writes the log first."""
    wal = db.with_name(db.name + "-wal")
    return tuple(p.stat().st_mtime_ns if p.exists() else None for p in (db, wal))


def change_probes(ctx: AppContext) -> dict[str, Callable[[], object]]:
    return {
        "posts": ctx.tools.posts.stamp,
        "store": lambda: _mtimes(ctx.settings.db_path),
    }
