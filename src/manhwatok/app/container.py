"""Composition root: builds adapters from settings. Imports adapters lazily so
`--help` stays fast."""

from __future__ import annotations

from typing import TYPE_CHECKING

from manhwatok.app.post_tools import EditorFn, PostTools, ProgressFn
from manhwatok.config import Settings
from manhwatok.domain.models import ArtSourceName, ChapterSourceName
from manhwatok.ports.art import ArtSource
from manhwatok.ports.cache import Cache
from manhwatok.ports.chapters import ChapterPagesSource
from manhwatok.ports.metadata import ChapterSource, MetadataSource
from manhwatok.ports.posts import PostRepository
from manhwatok.ports.uploader import Uploader

if TYPE_CHECKING:
    from manhwatok.adapters.sqlite_store import SqliteStore
    from manhwatok.app.chapter_post import ChapterTools


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


def build_art_sources(settings: Settings, cache: Cache) -> dict[ArtSourceName, ArtSource]:
    """Every place a title's art can come from, by the name the CLI and TUI call it.

    Both pair a title to their own catalogue first, and that pairing is cached in the database,
    since it does not change once made."""
    from manhwatok.adapters.booru import BooruSource
    from manhwatok.adapters.mangadex import MangaDexSource
    from manhwatok.adapters.pinterest import PinterestSource
    from manhwatok.adapters.reddit import RedditSource

    max_age = settings.art_cache_days * 24 * 3600
    return {
        ArtSourceName.COVERS: MangaDexSource(
            cache=cache, max_age=max_age, timeout=settings.http_timeout
        ),
        ArtSourceName.FANART: BooruSource(
            cache=cache, max_age=max_age, timeout=settings.http_timeout
        ),
        ArtSourceName.PINS: PinterestSource(),
        ArtSourceName.REDDIT: RedditSource(
            settings.reddit_client_id,
            settings.reddit_client_secret,
            settings.reddit_user,
            timeout=settings.http_timeout,
        ),
    }


def build_posts(settings: Settings) -> PostRepository:
    """Just the post folders — for commands that don't render (export, posts, delete)."""
    from manhwatok.adapters.fs_posts import FsPostRepository

    return FsPostRepository(settings.posts_dir)


def build_post_tools(
    settings: Settings,
    editor: EditorFn,
    progress: ProgressFn,
    metadata: MetadataSource | None = None,
    scenes: ArtSource | None = None,
) -> PostTools:
    """`metadata` and `scenes` default to new AniList and Pinterest sources (both cheap to make);
    a front end that already holds them passes its own."""
    from manhwatok.adapters.cover_cache import CoverCache
    from manhwatok.adapters.pillow_renderer import PillowRenderer
    from manhwatok.adapters.pinterest import PinterestSource
    from manhwatok.adapters.text_check import build_text_check

    return PostTools(
        posts=build_posts(settings),
        covers=CoverCache(settings.covers_dir, timeout=settings.http_timeout),
        renderer=PillowRenderer(),
        editor=editor,
        progress=progress,
        metadata=metadata or build_metadata(settings),
        scenes=scenes or PinterestSource(),
        has_text=build_text_check(),
    )


def build_chapter_sources(
    settings: Settings, cache: Cache
) -> dict[ChapterSourceName, ChapterPagesSource]:
    """Every place a chapter's pages can come from, by the name the CLI calls it.

    MangaDex first: it has the wider catalogue. WEBTOON is the publisher's own English, which
    is what a licensed title is missing on MangaDex — but only its free episodes."""
    from manhwatok.adapters.mangadex import MangaDexChapters
    from manhwatok.adapters.webtoons import WebtoonsChapters

    max_age = settings.art_cache_days * 24 * 3600
    return {
        ChapterSourceName.MANGADEX: MangaDexChapters(
            pages_dir=settings.pages_dir,
            cache=cache,
            max_age=max_age,
            timeout=settings.http_timeout,
        ),
        ChapterSourceName.WEBTOONS: WebtoonsChapters(
            pages_dir=settings.pages_dir,
            cache=cache,
            max_age=max_age,
            timeout=settings.http_timeout,
        ),
    }


def build_chapter_tools(settings: Settings, store: SqliteStore) -> ChapterTools:
    """The chapter feed, the panel cutter and the chapter table, bundled for the app layer."""
    from manhwatok.adapters.panel_cutter import PillowPanelCutter
    from manhwatok.app.chapter_post import ChapterTools

    sources = build_chapter_sources(settings, store.cache)
    return ChapterTools(
        pages=sources[ChapterSourceName.MANGADEX],
        cutter=PillowPanelCutter(),
        chapters=store.chapters,
        pages_dir=settings.pages_dir,
        source=ChapterSourceName.MANGADEX,
        sources=sources,
    )


def build_uploader(settings: Settings) -> Uploader:
    """The assisted-upload browser: a visible Google Chrome with one profile per account. Playwright
    itself is only imported once a browser is opened (it's the optional `upload` extra)."""
    from manhwatok.adapters.playwright_uploader import PlaywrightUploader

    return PlaywrightUploader(settings.browser_dir, settings.debug_dir)
