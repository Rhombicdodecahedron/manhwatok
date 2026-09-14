"""Key/value cache with per-read max age, in the app's SQLite database."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Callable


class SqliteCache:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._clock = clock
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS cache "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL, stored_at REAL NOT NULL)"
            )

    def get(self, key: str, max_age: float) -> str | None:
        row = self._conn.execute(
            "SELECT value, stored_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None or self._clock() - row[1] > max_age:
            return None
        return row[0]

    def put(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO cache (key, value, stored_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, stored_at = excluded.stored_at",
                (key, value, self._clock()),
            )
