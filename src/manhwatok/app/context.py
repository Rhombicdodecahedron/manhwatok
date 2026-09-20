"""One long-lived set of adapters for a front end that stays open (the TUI): built once,
shared by its worker threads, closed once on exit. CLI commands keep using `container`
directly, one command at a time."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from manhwatok.app import container
from manhwatok.app.chapter_post import ChapterTools
from manhwatok.app.names import AniListNames
from manhwatok.app.post_tools import PostTools
from manhwatok.config import Settings
from manhwatok.domain.models import ArtSourceName
from manhwatok.ports.art import ArtSource
from manhwatok.ports.metadata import ChapterSource, MetadataSource
from manhwatok.ports.uploader import Uploader

if TYPE_CHECKING:
    from manhwatok.adapters.sqlite_store import SqliteStore


def _no_editor(_: str) -> str | None:
    """The TUI edits picks in forms, never in $EDITOR."""
    return None


@dataclass
class AppContext:
    settings: Settings
    store: SqliteStore
    metadata: MetadataSource
    chapters: ChapterSource
    tools: PostTools
    art_sources: dict[ArtSourceName, ArtSource]
    chapter_tools: ChapterTools  # the chapter feed, the panel cutter and the chapter table
    uploader_factory: Callable[[], Uploader]
    closers: list[Any] = field(default_factory=list)  # objects with close(), closed in order
    _closed: bool = False

    def names(self, warn: Callable[[str], None]) -> AniListNames:
        return AniListNames(self.metadata, self.store.cache, warn)

    def uploader(self) -> Uploader:
        """A new browser helper for one login or upload (it closes its own browser)."""
        return self.uploader_factory()

    def close(self) -> None:
        """Close every adapter once; later calls do nothing."""
        if self._closed:
            return
        self._closed = True
        for item in self.closers:
            close = getattr(item, "close", None)
            if close is not None:
                close()


def open_context(settings: Settings) -> AppContext:
    store = container.build_store(settings)
    metadata = container.build_metadata(settings)
    chapters = container.build_chapter_source(settings, store.cache)
    art_sources = container.build_art_sources(settings, store.cache)
    chapter_tools = container.build_chapter_tools(settings, store)
    tools = container.build_post_tools(
        settings, _no_editor, lambda _: None, metadata, art_sources[ArtSourceName.PINS]
    )
    return AppContext(
        settings=settings,
        store=store,
        metadata=metadata,
        chapters=chapters,
        tools=tools,
        art_sources=art_sources,
        chapter_tools=chapter_tools,
        uploader_factory=lambda: container.build_uploader(settings),
        closers=[
            tools.covers,
            *art_sources.values(),
            chapter_tools.pages,
            chapters,
            metadata,
            store,
        ],
    )
