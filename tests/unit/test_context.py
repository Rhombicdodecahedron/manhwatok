import sqlite3

import httpx
import pytest

from manhwatok.adapters.anilist import AniListSource
from manhwatok.adapters.cached_chapters import CachedChapterSource
from manhwatok.adapters.cover_cache import CoverCache
from manhwatok.adapters.mangadex import MangaDexSource
from manhwatok.adapters.mangaupdates import MangaUpdatesSource
from manhwatok.adapters.pinterest import PinterestSource
from manhwatok.adapters.playwright_uploader import PlaywrightUploader
from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.context import open_context
from manhwatok.config import Settings
from manhwatok.adapters.booru import BooruSource
from manhwatok.domain.errors import StorageError
from manhwatok.domain.models import ArtSourceName
from tests.unit.fakes import FakeChapters


@pytest.mark.parametrize(
    "make",
    [
        lambda client, folder: AniListSource(client=client),
        lambda client, folder: MangaUpdatesSource(client=client),
        lambda client, folder: CoverCache(folder, client=client),
        lambda client, folder: MangaDexSource(client=client),
        lambda client, folder: BooruSource(client=client),
    ],
    ids=["anilist", "mangaupdates", "covers", "mangadex", "booru"],
)
def test_sources_close_only_the_client_they_created(make, tmp_path):
    given = httpx.Client()
    make(given, tmp_path).close()
    assert not given.is_closed
    given.close()
    own = make(None, tmp_path)
    own.close()
    assert own._client.is_closed


def test_cached_chapters_closes_the_inner_source_if_it_can(tmp_path):
    with SqliteStore(tmp_path / "m.db") as store:
        inner = MangaUpdatesSource()
        CachedChapterSource(inner, store.cache, 60).close()
        assert inner._client.is_closed
        CachedChapterSource(FakeChapters(), store.cache, 60).close()  # no close(): fine


def test_store_uses_wal(tmp_path):
    with SqliteStore(tmp_path / "m.db") as store:
        assert store.query(StorageError, "PRAGMA journal_mode") == [("wal",)]


def test_a_rollback_journal_database_is_switched_to_wal(tmp_path):
    path = tmp_path / "m.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    with SqliteStore(path) as store:
        assert store.query(StorageError, "PRAGMA journal_mode") == [("wal",)]


def test_open_context_wires_real_adapters_and_closes_them_once(tmp_path):
    ctx = open_context(Settings(data_dir=tmp_path))
    assert isinstance(ctx.store, SqliteStore)
    assert isinstance(ctx.metadata, AniListSource)
    assert isinstance(ctx.chapters, CachedChapterSource)
    assert isinstance(ctx.tools.covers, CoverCache)
    assert isinstance(ctx.art_sources[ArtSourceName.COVERS], MangaDexSource)
    assert isinstance(ctx.art_sources[ArtSourceName.FANART], BooruSource)
    assert isinstance(ctx.art_sources[ArtSourceName.PINS], PinterestSource)
    assert ctx.tools.editor("x") is None
    assert ctx.tools.posts.folder("20260914-a3f9") == tmp_path / "posts" / "20260914-a3f9"
    assert isinstance(ctx.uploader(), PlaywrightUploader)
    ctx.names(print).genres([])  # built on the context's metadata and cache
    ctx.close()
    assert ctx.metadata._client.is_closed
    assert ctx.tools.covers._client.is_closed
    assert ctx.chapters._inner._client.is_closed
    # Pinterest runs a process per search and holds no client, so only the HTTP-backed ones
    # have something to close.
    assert all(
        s._client.is_closed for s in ctx.art_sources.values() if hasattr(s, "_client")
    )
    assert ctx.art_sources[ArtSourceName.COVERS]._client.is_closed
    assert ctx.art_sources[ArtSourceName.FANART]._client.is_closed
    with pytest.raises(StorageError):
        ctx.store.accounts.list()
    ctx.close()  # second close does nothing
