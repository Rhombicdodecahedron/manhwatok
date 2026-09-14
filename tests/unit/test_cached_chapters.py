import pytest

from manhwatok.adapters.cached_chapters import CachedChapterSource
from manhwatok.adapters.sqlite_cache import SqliteCache
from manhwatok.domain.errors import MetadataError
from tests.unit.fakes import FakeChapters, manhwa
from tests.unit.test_sqlite_cache import Clock


def _cached(tmp_path, inner, clock):
    return CachedChapterSource(inner, SqliteCache(tmp_path / "c.db", clock=clock), max_age=3600)


def test_second_lookup_hits_cache(tmp_path):
    inner = FakeChapters({7: 55})
    src = _cached(tmp_path, inner, Clock())
    assert src.latest_chapter(manhwa(anilist_id=7)) == 55
    assert src.latest_chapter(manhwa(anilist_id=7)) == 55
    assert inner.calls == [7]


def test_not_found_is_cached_too(tmp_path):
    inner = FakeChapters({})
    src = _cached(tmp_path, inner, Clock())
    assert src.latest_chapter(manhwa(anilist_id=8)) is None
    assert src.latest_chapter(manhwa(anilist_id=8)) is None
    assert inner.calls == [8]


def test_expired_entry_refetches(tmp_path):
    clock = Clock()
    inner = FakeChapters({7: 55})
    src = _cached(tmp_path, inner, clock)
    src.latest_chapter(manhwa(anilist_id=7))
    clock.now += 3601
    inner.latest[7] = 56
    assert src.latest_chapter(manhwa(anilist_id=7)) == 56
    assert inner.calls == [7, 7]


def test_errors_are_not_cached(tmp_path):
    inner = FakeChapters(error=MetadataError("down"))
    src = _cached(tmp_path, inner, Clock())
    with pytest.raises(MetadataError):
        src.latest_chapter(manhwa(anilist_id=7))
    inner.error = None
    inner.latest[7] = 55
    assert src.latest_chapter(manhwa(anilist_id=7)) == 55
