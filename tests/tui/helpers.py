"""Running the TUI headless against fakes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.context import AppContext
from manhwatok.config import Settings
from manhwatok.domain.models import ArtSourceName
from tests.unit.fakes import (
    FakeArtSource,
    FakeChapters,
    FakeMetadata,
    FakeRenderer,
    make_chapter_tools,
    FakeUploader,
    make_tools,
)

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
OPEN_CONTEXTS: list[AppContext] = []  # closed after each test (conftest)


class PngRenderer(FakeRenderer):
    """FakeRenderer whose slides are real (tiny, 9:16) PNGs, so the preview can load them."""

    def render(self, post, art, out_dir):
        from PIL import Image

        from manhwatok.domain.models import CoverStyle

        paths = super().render(post, art, out_dir)
        for n, path in enumerate(paths):
            Image.new("RGB", (27, 48), (40 * n % 255, 80, 120)).save(path)
        for old in out_dir.glob("cover-*.png"):
            old.unlink()
        for k, style in enumerate(CoverStyle):
            version = out_dir / f"cover-{style.value}.png"
            Image.new("RGB", (27, 48), (200, 60 * k, 10)).save(version)
            if style is post.cover:
                paths[0].write_bytes(version.read_bytes())
        return paths


def make_ctx(
    tmp_path: Path,
    metadata=None,
    uploader=None,
    covers=None,
    art=None,
    fanart=None,
    pins=None,
    reddit=None,
    chapter_pages=None,
) -> AppContext:
    """A context on a real database and real post folders under tmp_path, fakes elsewhere.
    Every `uploader()` call returns the same `uploader` (a FakeUploader by default)."""
    store = SqliteStore(tmp_path / "manhwatok.db")
    browser = uploader or FakeUploader()
    ctx = AppContext(
        settings=Settings(data_dir=tmp_path, export_dir=tmp_path / "exports"),
        store=store,
        metadata=metadata or FakeMetadata(),
        chapters=FakeChapters(),
        tools=make_tools(tmp_path, covers=covers, renderer=PngRenderer()),
        art_sources={
            ArtSourceName.COVERS: art or FakeArtSource(),
            ArtSourceName.FANART: fanart or FakeArtSource(),
            ArtSourceName.PINS: pins or FakeArtSource(),
            ArtSourceName.REDDIT: reddit or FakeArtSource(),
        },
        chapter_tools=make_chapter_tools(
            tmp_path, pages=chapter_pages, chapters=store.chapters
        ),
        uploader_factory=lambda: browser,
        closers=[store],
    )
    OPEN_CONTEXTS.append(ctx)
    return ctx


class Opened(list):
    """Stands in for xdg-open: remembers the paths."""

    def __call__(self, path: Path) -> None:
        self.append(path)


def run_app(ctx: AppContext, scenario: Callable, size=(140, 45), opener=None) -> None:
    """Run `await scenario(app, pilot)` inside a headless app. The context stays open until
    the test ends, so the test can check the database afterwards."""
    from manhwatok.tui.app import ManhwatokApp

    app = ManhwatokApp(ctx, opener=Opened() if opener is None else opener, clock=lambda: NOW)
    shown: list[str] = []
    notify = app.notify

    def remember(message, **kwargs):
        shown.append(str(message))
        notify(message, **kwargs)

    app.notify = remember
    app.shown_notes = shown

    async def main() -> None:
        async with app.run_test(size=size) as pilot:
            await scenario(app, pilot)

    asyncio.run(main())


async def wait_for(pilot, condition: Callable[[], bool], timeout: float = 5.0) -> None:
    """Let the app run until `condition()` holds (worker threads finish on their own time)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise AssertionError("timed out waiting for the app")
        await pilot.pause(0.05)


def notes(app) -> list[str]:
    """Every notification message shown so far (also the ones that timed out)."""
    return list(app.shown_notes)


Scenario = Callable[..., Awaitable[None]]
