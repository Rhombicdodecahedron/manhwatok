import re
import sqlite3
import threading

import pytest

from manhwatok.adapters import sqlite_store
from manhwatok.adapters.sqlite_store import MIGRATIONS, SCHEMA_VERSION, SqliteStore
from manhwatok.domain.errors import CacheError, StorageError
from tests.unit.fakes import Clock


def _version(path) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def _tables(path) -> set[str]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")
        return {name for (name,) in rows if not name.startswith("sqlite_")}


# --- schema --------------------------------------------------------------------------------


def test_fresh_database_is_migrated_to_latest(tmp_path):
    path = tmp_path / "m.db"
    SqliteStore(path).close()
    assert SCHEMA_VERSION == 2
    assert _version(path) == 2
    assert _tables(path) == {"cache", "accounts", "themes", "history", "history_by_account_date"}


def test_phase2_database_is_upgraded_in_place_and_keeps_cache_rows(tmp_path):
    """Phase 2's SqliteCache created `cache` itself and never set user_version."""
    path = tmp_path / "manhwatok.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL, stored_at REAL NOT NULL)"
        )
        conn.execute("INSERT INTO cache VALUES ('latest_chapter:7', '55', 1000.0)")
        conn.execute("INSERT INTO cache VALUES ('latest_chapter:8', 'null', 1000.0)")
    conn.close()
    assert _version(path) == 0

    with SqliteStore(path, clock=Clock(1010.0)) as store:
        assert store.cache.get("latest_chapter:7", 60) == "55"
        assert store.cache.get("latest_chapter:8", 60) == "null"
    assert _version(path) == 2
    assert {"accounts", "themes", "history"} <= _tables(path)


def test_reopening_keeps_data_and_version(tmp_path):
    path = tmp_path / "m.db"
    with SqliteStore(path) as store:
        store.cache.put("k", "v")
    with SqliteStore(path) as store:
        assert store.cache.get("k", 60) == "v"
    assert _version(path) == 2


def test_database_from_a_newer_version_is_refused(tmp_path):
    path = tmp_path / "m.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(StorageError, match="schema v99"):
        SqliteStore(path)


def test_failed_migration_rolls_back_completely(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    broken = "CREATE TABLE half_done (x INTEGER); INSERT INTO no_such_table VALUES (1);"
    monkeypatch.setattr(sqlite_store, "MIGRATIONS", (MIGRATIONS[0], broken))
    monkeypatch.setattr(sqlite_store, "SCHEMA_VERSION", 2)
    with pytest.raises(StorageError, match="could not upgrade"):
        SqliteStore(path)
    assert _version(path) == 1
    assert "half_done" not in _tables(path)


def test_unusable_path_raises_storage_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    bad_path = blocker / "sub" / "m.db"
    with pytest.raises(StorageError, match=re.escape(str(bad_path))):
        SqliteStore(bad_path)


def test_corrupt_database_file_raises_storage_error(tmp_path):
    path = tmp_path / "m.db"
    path.write_bytes(b"this is not a database" * 100)
    with pytest.raises(StorageError, match=re.escape(str(path))):
        SqliteStore(path)


def test_creates_parent_dirs(tmp_path):
    path = tmp_path / "a" / "b" / "m.db"
    SqliteStore(path).close()
    assert path.is_file()


def test_connection_can_be_used_from_another_thread(tmp_path):
    store = SqliteStore(tmp_path / "m.db")
    errors = []

    def worker():
        try:
            store.cache.put("k", "from thread")
        except Exception as e:  # surfaced by the assert below
            errors.append(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert errors == []
    assert store.cache.get("k", 60) == "from thread"
    store.close()


# --- cache (moved from the Phase 2 SqliteCache tests) --------------------------------------


def test_cache_miss_returns_none(tmp_path):
    assert SqliteStore(tmp_path / "m.db").cache.get("k", 60) is None


def test_cache_put_then_get(tmp_path):
    cache = SqliteStore(tmp_path / "m.db").cache
    cache.put("k", "v")
    assert cache.get("k", 60) == "v"


def test_cache_expired_entry_is_a_miss(tmp_path):
    clock = Clock()
    cache = SqliteStore(tmp_path / "m.db", clock=clock).cache
    cache.put("k", "v")
    clock.now += 61
    assert cache.get("k", 60) is None


def test_cache_put_overwrites_and_refreshes_age(tmp_path):
    clock = Clock()
    cache = SqliteStore(tmp_path / "m.db", clock=clock).cache
    cache.put("k", "old")
    clock.now += 50
    cache.put("k", "new")
    clock.now += 50
    assert cache.get("k", 60) == "new"


def test_cache_errors_after_close_are_cache_errors(tmp_path):
    path = tmp_path / "m.db"
    with SqliteStore(path) as store:
        pass
    with pytest.raises(CacheError, match=re.escape(str(path))):
        store.cache.get("k", 60)
    with pytest.raises(CacheError, match=re.escape(str(path))):
        store.cache.put("k", "v")
