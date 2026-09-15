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


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    with SqliteStore(tmp_path / "c.db", clock=clock) as s:
        yield s


def _cached(store, inner):
    return CachedChapterSource(inner, store.cache, max_age=3600)


def test_second_lookup_hits_cache(store):
    inner = FakeChapters({7: 55})
    src = _cached(store, inner)
    assert src.latest_chapter(manhwa(anilist_id=7)) == 55
    assert src.latest_chapter(manhwa(anilist_id=7)) == 55
    assert inner.calls == [7]


def test_not_found_is_cached_too(store):
    inner = FakeChapters({})
    src = _cached(store, inner)
    assert src.latest_chapter(manhwa(anilist_id=8)) is None
    assert src.latest_chapter(manhwa(anilist_id=8)) is None
    assert inner.calls == [8]


def test_expired_entry_refetches(store, clock):
    inner = FakeChapters({7: 55})
    src = _cached(store, inner)
    src.latest_chapter(manhwa(anilist_id=7))
    clock.now += 3601
    inner.latest[7] = 56
    assert src.latest_chapter(manhwa(anilist_id=7)) == 56
    assert inner.calls == [7, 7]


def test_cache_get_error_is_treated_as_a_miss_and_put_error_is_ignored():
    inner = FakeChapters({7: 55})
    src = CachedChapterSource(inner, BrokenCache(), max_age=3600)
    assert src.latest_chapter(manhwa(anilist_id=7)) == 55
    assert inner.calls == [7]


def test_errors_are_not_cached(store):
    inner = FakeChapters(error=MetadataError("down"))
    src = _cached(store, inner)
    with pytest.raises(MetadataError):
        src.latest_chapter(manhwa(anilist_id=7))
    inner.error = None
    inner.latest[7] = 55
    assert src.latest_chapter(manhwa(anilist_id=7)) == 55


@pytest.mark.parametrize("corrupt", ["not json", '"55"', "[55]", "true", "5.5"])
def test_corrupt_cached_value_is_a_miss_and_gets_overwritten(store, corrupt):
    inner = FakeChapters({7: 55})
    src = _cached(store, inner)
    src.latest_chapter(manhwa(anilist_id=7))
    store.write(CacheError, "UPDATE cache SET value = ?", (corrupt,))
    assert src.latest_chapter(manhwa(anilist_id=7)) == 55
    assert src.latest_chapter(manhwa(anilist_id=7)) == 55
    assert inner.calls == [7, 7]
