"""Composition root: builds adapters from settings. Imports adapters lazily so
`--help` stays fast."""

from __future__ import annotations

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
