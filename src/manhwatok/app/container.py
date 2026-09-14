"""Composition root: builds adapters from settings. Imports adapters lazily so
`--help` stays fast."""

from __future__ import annotations

from manhwatok.app.post_tools import EditorFn, PostTools, ProgressFn
from manhwatok.config import Settings
from manhwatok.ports.metadata import ChapterSource, MetadataSource


def build_metadata(settings: Settings) -> MetadataSource:
    from manhwatok.adapters.anilist import AniListSource

    return AniListSource(timeout=settings.http_timeout)


def build_chapter_source(settings: Settings) -> ChapterSource:
    from manhwatok.adapters.cached_chapters import CachedChapterSource
    from manhwatok.adapters.mangaupdates import MangaUpdatesSource
    from manhwatok.adapters.sqlite_cache import SqliteCache

    return CachedChapterSource(
        MangaUpdatesSource(timeout=settings.http_timeout),
        SqliteCache(settings.db_path),
        max_age=settings.chapter_cache_hours * 3600,
    )


def build_post_tools(settings: Settings, editor: EditorFn, progress: ProgressFn) -> PostTools:
    from manhwatok.adapters.cover_cache import CoverCache
    from manhwatok.adapters.fs_posts import FsPostRepository
    from manhwatok.adapters.pillow_renderer import PillowRenderer

    return PostTools(
        posts=FsPostRepository(settings.posts_dir),
        covers=CoverCache(settings.covers_dir, timeout=settings.http_timeout),
        renderer=PillowRenderer(),
        editor=editor,
        progress=progress,
    )
