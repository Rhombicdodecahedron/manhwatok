"""Composition root: builds adapters from settings. Imports adapters lazily so
`--help` stays fast."""

from __future__ import annotations

from typing import TYPE_CHECKING

from manhwatok.app.post_tools import EditorFn, PostTools, ProgressFn
from manhwatok.config import Settings
from manhwatok.ports.cache import Cache
from manhwatok.ports.metadata import ChapterSource, MetadataSource
from manhwatok.ports.posts import PostRepository
from manhwatok.ports.uploader import Uploader

if TYPE_CHECKING:
    from manhwatok.adapters.sqlite_store import SqliteStore


def build_store(settings: Settings) -> SqliteStore:
    """The database (cache, accounts, themes, history). One per command; close it
    (`with build_store(settings) as store:`)."""
    from manhwatok.adapters.sqlite_store import SqliteStore

    return SqliteStore(settings.db_path)


def build_metadata(settings: Settings) -> MetadataSource:
    from manhwatok.adapters.anilist import AniListSource

    return AniListSource(timeout=settings.http_timeout)


def build_chapter_source(settings: Settings, cache: Cache) -> ChapterSource:
    from manhwatok.adapters.cached_chapters import CachedChapterSource
    from manhwatok.adapters.mangaupdates import MangaUpdatesSource

    return CachedChapterSource(
        MangaUpdatesSource(timeout=settings.http_timeout),
        cache,
        max_age=settings.chapter_cache_hours * 3600,
    )


def build_posts(settings: Settings) -> PostRepository:
    """Just the post folders — for commands that don't render (export, posts, delete)."""
    from manhwatok.adapters.fs_posts import FsPostRepository

    return FsPostRepository(settings.posts_dir)


def build_post_tools(settings: Settings, editor: EditorFn, progress: ProgressFn) -> PostTools:
    from manhwatok.adapters.cover_cache import CoverCache
    from manhwatok.adapters.pillow_renderer import PillowRenderer

    return PostTools(
        posts=build_posts(settings),
        covers=CoverCache(settings.covers_dir, timeout=settings.http_timeout),
        renderer=PillowRenderer(),
        editor=editor,
        progress=progress,
    )


def build_uploader(settings: Settings) -> Uploader:
    """The assisted-upload browser: a visible Google Chrome with one profile per account. Playwright
    itself is only imported once a browser is opened (it's the optional `upload` extra)."""
    from manhwatok.adapters.playwright_uploader import PlaywrightUploader

    return PlaywrightUploader(settings.browser_dir, settings.debug_dir)
