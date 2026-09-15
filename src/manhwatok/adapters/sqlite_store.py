"""The app's SQLite database (manhwatok.db): one owner of the connection, a versioned schema,
and one small table class per port."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from manhwatok.domain.errors import CacheError, ManhwatokError, StorageError

# MIGRATIONS[n - 1] takes the schema from PRAGMA user_version n-1 to n. Never edit a shipped
# migration; append a new one. v1 says IF NOT EXISTS because Phase 2's SqliteCache created the
# `cache` table without ever setting user_version, so those databases start here at 0.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS cache (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, stored_at REAL NOT NULL
    );
    """,
    """
    CREATE TABLE accounts (handle TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE themes (name TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE history (
        account TEXT NOT NULL,
        anilist_id INTEGER NOT NULL,
        post_id TEXT NOT NULL,
        exported_at TEXT NOT NULL,
        PRIMARY KEY (account, anilist_id, post_id)
    );
    CREATE INDEX history_by_account_date ON history (account, exported_at);
    """,
)
SCHEMA_VERSION = len(MIGRATIONS)

Rows = list[tuple]


def _migrate(conn: sqlite3.Connection, path: Path) -> None:
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise StorageError(
                f"database at {path} has schema v{version}, newer than this manhwatok "
                f"(v{SCHEMA_VERSION}) — update manhwatok"
            )
        for target in range(version + 1, SCHEMA_VERSION + 1):
            try:
                # one transaction per step: the tables and the version bump land together
                conn.executescript(
                    f"BEGIN;\n{MIGRATIONS[target - 1]}\nPRAGMA user_version = {target};\nCOMMIT;"
                )
            except sqlite3.Error:
                if conn.in_transaction:
                    conn.rollback()
                raise
    except sqlite3.Error as e:
        raise StorageError(f"could not upgrade database at {path}: {e}") from e


class SqliteStore:
    """Owns the only connection to manhwatok.db. Use one per command (or per worker thread
    owner) and close it: `with SqliteStore(path) as store: ...`."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False)
        except (sqlite3.Error, OSError) as e:
            raise StorageError(f"database at {path} is unusable: {e}") from e
        try:
            _migrate(conn, path)
        except StorageError:
            conn.close()
            raise
        self._conn = conn
        self._lock = threading.RLock()  # the connection may be shared by worker threads
        self.cache = CacheTable(self, clock)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def query(self, error: type[ManhwatokError], sql: str, params: tuple = ()) -> Rows:
        try:
            with self._lock:
                return self._conn.execute(sql, params).fetchall()
        except (sqlite3.Error, OSError) as e:
            raise error(f"database at {self.path} is unusable: {e}") from e

    def write(self, error: type[ManhwatokError], sql: str, params: tuple = ()) -> int:
        """Run one statement in its own transaction; returns the number of changed rows."""
        try:
            with self._lock, self._conn:
                return self._conn.execute(sql, params).rowcount
        except (sqlite3.Error, OSError) as e:
            raise error(f"database at {self.path} is unusable: {e}") from e


class CacheTable:
    """The `Cache` port: key/value strings with a per-read max age."""

    def __init__(self, store: SqliteStore, clock: Callable[[], float]) -> None:
        self._store = store
        self._clock = clock

    def get(self, key: str, max_age: float) -> str | None:
        rows = self._store.query(
            CacheError, "SELECT value, stored_at FROM cache WHERE key = ?", (key,)
        )
        if not rows or self._clock() - rows[0][1] > max_age:
            return None
        return rows[0][0]

    def put(self, key: str, value: str) -> None:
        self._store.write(
            CacheError,
            "INSERT INTO cache (key, value, stored_at) VALUES (?, ?, ?) ON CONFLICT(key) "
            "DO UPDATE SET value = excluded.value, stored_at = excluded.stored_at",
            (key, value, self._clock()),
        )
