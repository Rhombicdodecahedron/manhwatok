import re

import pytest

from manhwatok.adapters.sqlite_cache import SqliteCache
from manhwatok.domain.errors import CacheError


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_miss_returns_none(tmp_path):
    assert SqliteCache(tmp_path / "c.db").get("k", 60) is None


def test_put_then_get(tmp_path):
    cache = SqliteCache(tmp_path / "c.db")
    cache.put("k", "v")
    assert cache.get("k", 60) == "v"


def test_expired_entry_is_a_miss(tmp_path):
    clock = Clock()
    cache = SqliteCache(tmp_path / "c.db", clock=clock)
    cache.put("k", "v")
    clock.now += 61
    assert cache.get("k", 60) is None


def test_put_overwrites_and_refreshes_age(tmp_path):
    clock = Clock()
    cache = SqliteCache(tmp_path / "c.db", clock=clock)
    cache.put("k", "old")
    clock.now += 50
    cache.put("k", "new")
    clock.now += 50
    assert cache.get("k", 60) == "new"


def test_persists_across_instances_and_creates_parent_dirs(tmp_path):
    path = tmp_path / "a" / "b" / "c.db"
    SqliteCache(path).put("k", "v")
    assert SqliteCache(path).get("k", 60) == "v"


def test_unusable_path_raises_cache_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    bad_path = blocker / "sub" / "c.db"
    with pytest.raises(CacheError, match=re.escape(str(bad_path))):
        SqliteCache(bad_path)


def test_get_wraps_sqlite_errors_in_cache_error(tmp_path):
    path = tmp_path / "c.db"
    cache = SqliteCache(path)
    cache._conn.close()
    with pytest.raises(CacheError, match=re.escape(str(path))):
        cache.get("k", 60)


def test_put_wraps_sqlite_errors_in_cache_error(tmp_path):
    path = tmp_path / "c.db"
    cache = SqliteCache(path)
    cache._conn.close()
    with pytest.raises(CacheError, match=re.escape(str(path))):
        cache.put("k", "v")
