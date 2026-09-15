import pytest

from manhwatok.adapters.cached_chapters import CachedChapterSource
from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.domain.errors import CacheError, MetadataError
from tests.unit.fakes import Clock, FakeChapters, manhwa


class BrokenCache:
    """Raises CacheError on every get and put — simulates a locked/unwritable DB."""

    def get(self, key: str, max_age: float) -> str | None:
        raise CacheError("cache unavailable")

    def put(self, key: str, value: str) -> None:
        raise CacheError("cache unavailable")


def _cached(tmp_path, inner, clock):
    cache = SqliteStore(tmp_path / "c.db", clock=clock).cache
    return CachedChapterSource(inner, cache, max_age=3600)


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


def test_cache_get_error_is_treated_as_a_miss_and_put_error_is_ignored(tmp_path):
    inner = FakeChapters({7: 55})
    src = CachedChapterSource(inner, BrokenCache(), max_age=3600)
    assert src.latest_chapter(manhwa(anilist_id=7)) == 55
    assert inner.calls == [7]


def test_errors_are_not_cached(tmp_path):
    inner = FakeChapters(error=MetadataError("down"))
    src = _cached(tmp_path, inner, Clock())
    with pytest.raises(MetadataError):
        src.latest_chapter(manhwa(anilist_id=7))
    inner.error = None
    inner.latest[7] = 55
    assert src.latest_chapter(manhwa(anilist_id=7)) == 55


@pytest.mark.parametrize("corrupt", ["not json", '"55"', "[55]", "true", "5.5"])
def test_corrupt_cached_value_is_a_miss_and_gets_overwritten(tmp_path, corrupt):
    inner = FakeChapters({7: 55})
    with SqliteStore(tmp_path / "c.db", clock=Clock()) as store:
        src = CachedChapterSource(inner, store.cache, max_age=3600)
        src.latest_chapter(manhwa(anilist_id=7))
        store.write(CacheError, "UPDATE cache SET value = ?", (corrupt,))
        assert src.latest_chapter(manhwa(anilist_id=7)) == 55
        assert src.latest_chapter(manhwa(anilist_id=7)) == 55
    assert inner.calls == [7, 7]
