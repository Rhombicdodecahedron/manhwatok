import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from manhwatok.adapters import sqlite_store
from manhwatok.adapters.sqlite_store import MIGRATIONS, SCHEMA_VERSION, SqliteStore
from manhwatok.domain.account import Account
from manhwatok.domain.errors import (
    AccountNotFound,
    AlreadyExists,
    CacheError,
    StorageError,
    ThemeNotFound,
)
from manhwatok.domain.theme import Theme
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


def _phase2_database(path, rows: int = 3) -> None:
    """A database as Phase 2 left it: only `cache`, user_version 0."""
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE TABLE cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, stored_at REAL NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO cache VALUES (?, ?, 1000.0)",
            [(f"latest_chapter:{i}", str(i)) for i in range(rows)],
        )


def test_concurrent_openers_upgrade_a_phase2_database_exactly_once(tmp_path):
    """Several commands starting at once on an old database (e.g. two terminals after an
    update): every one opens it, each migration step runs once, nothing is lost."""
    openers, trials = 6, 20
    failures: list[str] = []
    for trial in range(trials):
        path = tmp_path / f"m{trial}.db"
        _phase2_database(path)
        barrier = threading.Barrier(openers)

        def open_store(path=path, barrier=barrier, trial=trial) -> None:
            barrier.wait()
            try:
                SqliteStore(path).close()
            except StorageError as e:
                failures.append(f"trial {trial}: {e}")

        threads = [threading.Thread(target=open_store) for _ in range(openers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with closing(sqlite3.connect(path)) as conn:
            state = (
                conn.execute("PRAGMA user_version").fetchone()[0],
                conn.execute("PRAGMA integrity_check").fetchone()[0],
                conn.execute("SELECT key, value FROM cache ORDER BY key").fetchall(),
            )
        if state != (2, "ok", [(f"latest_chapter:{i}", str(i)) for i in range(3)]):
            failures.append(f"trial {trial}: user_version/integrity/rows = {state}")
    assert failures == []


def test_connections_wait_for_a_busy_database(tmp_path):
    with SqliteStore(tmp_path / "m.db") as store:
        assert store.query(StorageError, "PRAGMA busy_timeout") == [(10_000,)]


def test_migration_scripts_split_into_single_statements():
    script = """
    CREATE TABLE a (x TEXT DEFAULT 'semi;colon');
    CREATE INDEX a_x ON a (x);
    INSERT INTO a VALUES ('no trailing semicolon')"""
    assert sqlite_store._statements(script) == [
        "CREATE TABLE a (x TEXT DEFAULT 'semi;colon');",
        "CREATE INDEX a_x ON a (x);",
        "INSERT INTO a VALUES ('no trailing semicolon');",
    ]
    assert [len(sqlite_store._statements(m)) for m in MIGRATIONS] == [1, 4]


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


# --- accounts and themes -------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    with SqliteStore(tmp_path / "m.db") as s:
        yield s


def test_accounts_round_trip_sorted_by_handle(store):
    b = Account(handle="bravo", genres=["Action"], repeat_days=7)
    a = Account(handle="alpha", block_tags=["Harem"])
    store.accounts.add(b)
    store.accounts.add(a)
    assert store.accounts.get("bravo") == b
    assert store.accounts.list() == [a, b]


def test_account_update_and_remove(store):
    store.accounts.add(Account(handle="alpha"))
    store.accounts.update(Account(handle="alpha", hashtags="#x"))
    assert store.accounts.get("alpha").hashtags == "#x"
    store.accounts.remove("alpha")
    assert store.accounts.list() == []


def test_adding_an_existing_account_fails(store):
    store.accounts.add(Account(handle="alpha"))
    with pytest.raises(AlreadyExists, match="account @alpha already exists"):
        store.accounts.add(Account(handle="alpha", hashtags="#other"))
    assert store.accounts.get("alpha").hashtags != "#other"


@pytest.mark.parametrize("op", ["get", "remove", "update"])
def test_missing_account(store, op):
    arg = Account(handle="ghost") if op == "update" else "ghost"
    with pytest.raises(AccountNotFound, match="no account @ghost"):
        getattr(store.accounts, op)(arg)


def test_themes_round_trip_and_errors(store):
    t = Theme(name="revenge", tags=["Revenge"], title="MC gets *revenge*")
    store.themes.add(t)
    assert store.themes.get("revenge") == t
    assert store.themes.list() == [t]
    with pytest.raises(AlreadyExists, match="theme revenge already exists"):
        store.themes.add(t)
    store.themes.update(t.model_copy(update={"title": "New"}))
    assert store.themes.get("revenge").title == "New"
    store.themes.remove("revenge")
    with pytest.raises(ThemeNotFound, match="no theme revenge"):
        store.themes.get("revenge")


def test_corrupt_row_raises_storage_error(store):
    store.write(StorageError, "INSERT INTO accounts VALUES ('alpha', '{\"handle\": \"!\"}')")
    with pytest.raises(StorageError, match="account @alpha .* is unreadable"):
        store.accounts.get("alpha")
    with pytest.raises(StorageError, match="unreadable"):
        store.accounts.list()


def test_repository_errors_after_close_are_storage_errors(tmp_path):
    with SqliteStore(tmp_path / "m.db") as closed:
        pass
    with pytest.raises(StorageError, match="unusable"):
        closed.accounts.list()
    with pytest.raises(StorageError, match="unusable"):
        closed.history.recent("alpha", datetime(2026, 1, 1, tzinfo=timezone.utc))


# --- history -------------------------------------------------------------------------------

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def test_recent_returns_ids_exported_since(store):
    store.history.record("alpha", "20260901-aaaa", [1, 2], T0)
    store.history.record("alpha", "20260911-bbbb", [3], T0 + timedelta(days=10))
    assert store.history.recent("alpha", T0) == {1, 2, 3}
    assert store.history.recent("alpha", T0 + timedelta(days=5)) == {3}


def test_recent_window_boundary_is_inclusive(store):
    store.history.record("alpha", "20260901-aaaa", [1], T0)
    assert store.history.recent("alpha", T0) == {1}
    assert store.history.recent("alpha", T0 + timedelta(microseconds=1)) == set()
    assert store.history.recent("alpha", T0 - timedelta(microseconds=1)) == {1}


def test_recent_compares_instants_across_timezones(store):
    store.history.record("alpha", "20260901-aaaa", [1], T0)
    plus_two = timezone(timedelta(hours=2))
    assert store.history.recent("alpha", datetime(2026, 9, 1, 14, 0, tzinfo=plus_two)) == {1}
    assert store.history.recent("alpha", datetime(2026, 9, 1, 14, 1, tzinfo=plus_two)) == set()


def test_history_is_per_account(store):
    store.history.record("alpha", "20260901-aaaa", [1], T0)
    assert store.history.recent("bravo", T0) == set()


def test_record_is_idempotent_and_keeps_the_first_date(store):
    store.history.record("alpha", "20260901-aaaa", [1, 2], T0)
    store.history.record("alpha", "20260901-aaaa", [1, 2], T0 + timedelta(days=10))
    assert store.query(StorageError, "SELECT COUNT(*) FROM history") == [(2,)]
    assert store.history.recent("alpha", T0 + timedelta(days=5)) == set()


def test_removing_an_account_keeps_its_history(store):
    store.accounts.add(Account(handle="alpha"))
    store.history.record("alpha", "20260901-aaaa", [1], T0)
    store.accounts.remove("alpha")
    assert store.history.recent("alpha", T0) == {1}
