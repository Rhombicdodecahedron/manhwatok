"""One long-lived set of adapters for a front end that stays open (the TUI): built once,
shared by its worker threads, closed once on exit. CLI commands keep using `container`
directly, one command at a time."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable

from manhwatok.app import container
from manhwatok.app.chapter_post import ChapterTools
from manhwatok.app.names import AniListNames
from manhwatok.app.post_tools import PostTools, ProgressFn
from manhwatok.config import Settings
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import ArtSourceName
from manhwatok.ports.art import ArtSource
from manhwatok.ports.metadata import ChapterSource, MetadataSource
from manhwatok.ports.uploader import Uploader

if TYPE_CHECKING:
    from manhwatok.adapters.sqlite_store import SqliteStore


# The upload modes the app switches between, as its header names them.
UPLOAD_MODE_LABELS = {
    "browser": "browser",
    "phone": "phone",
    "phone-post": "phone, posting and sharing to the Story",
}


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
    # Builds an uploader from settings: per upload, for the mode and phone chosen then.
    uploader_with: Callable[[Settings], Uploader] = field(default=container.build_uploader)
    closers: list[Any] = field(default_factory=list)  # objects with close(), closed in order
    _closed: bool = False

    def names(self, warn: Callable[[str], None]) -> AniListNames:
        return AniListNames(self.metadata, self.store.cache, warn)

    def uploader(self) -> Uploader:
        """A new browser (or phone) helper for one login or upload; it closes its own."""
        return self.uploader_factory()

    def uploader_for(self, mode: str, phone: str = "") -> Uploader:
        """An uploader for `mode` ("browser", "phone", "phone-post") on `phone` (a serial, or
        "" for the only one), leaving the app's own settings as they are."""
        if mode not in UPLOAD_MODE_LABELS:
            raise ManhwatokError(f"no upload mode {mode!r}")
        settings = replace(
            self.settings,
            uploader=mode.removesuffix("-post"),
            auto_post=mode.endswith("-post"),
            phone=phone,
        )
        return self.uploader_with(settings)

    @property
    def upload_mode(self) -> str:
        """How logins and uploads go: "browser", "phone", or "phone-post" — the phone, tapping
        Post itself (MANHWATOK_UPLOADER and MANHWATOK_AUTO_POST to start with)."""
        mode = self.settings.uploader
        return f"{mode}-post" if mode == "phone" and self.settings.auto_post else mode

    @property
    def upload_mode_label(self) -> str:
        return UPLOAD_MODE_LABELS.get(self.upload_mode, self.upload_mode)

    def set_upload_mode(self, mode: str) -> None:
        """Switch the next logins and uploads to `mode`, for as long as the app stays open;
        one already under way keeps going the way it started."""
        if mode not in UPLOAD_MODE_LABELS:
            modes = ", ".join(UPLOAD_MODE_LABELS)
            raise ManhwatokError(f"no upload mode {mode!r} — use one of: {modes}")
        self.settings.uploader = mode.removesuffix("-post")
        self.settings.auto_post = mode.endswith("-post")

    def close(self) -> None:
        """Close every adapter once; later calls do nothing."""
        if self._closed:
            return
        self._closed = True
        for item in self.closers:
            close = getattr(item, "close", None)
            if close is not None:
                close()


def _quiet(_: str) -> None:
    pass


def open_context(settings: Settings, progress: ProgressFn = _quiet) -> AppContext:
    """`progress`: where the post tools report what they do (the TUI's workers pass their
    own per job; a command passes its progress line)."""
    store = container.build_store(settings)
    metadata = container.build_metadata(settings)
    chapters = container.build_chapter_source(settings, store.cache)
    art_sources = container.build_art_sources(settings, store.cache)
    chapter_tools = container.build_chapter_tools(settings, store)
    tools = container.build_post_tools(
        settings, _no_editor, progress, metadata, art_sources[ArtSourceName.PINS]
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
            *chapter_tools.sources.values(),
            chapters,
            metadata,
            store,
        ],
    )
