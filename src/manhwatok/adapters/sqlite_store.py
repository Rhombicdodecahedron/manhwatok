"""The app's SQLite database (manhwatok.db): one owner of the connection, a versioned schema,
and one small table class per port."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from manhwatok.domain.account import Account
from manhwatok.domain.errors import (
    AccountNotFound,
    AlreadyExists,
    CacheError,
    ManhwatokError,
    StorageError,
    ThemeNotFound,
)
from manhwatok.domain.chapter import ChapterRecord, PartRecord, chapter_sort_key
from manhwatok.domain.theme import Theme

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
    """
    CREATE TABLE chapters (
        anilist_id INTEGER NOT NULL,
        number TEXT NOT NULL,
        language TEXT NOT NULL,
        chapter_id TEXT NOT NULL,
        manhwa_title TEXT NOT NULL DEFAULT '',
        chapter_title TEXT NOT NULL DEFAULT '',
        pages INTEGER NOT NULL DEFAULT 0,
        downloaded_at TEXT,
        PRIMARY KEY (anilist_id, number, language)
    );
    CREATE TABLE chapter_parts (
        anilist_id INTEGER NOT NULL,
        number TEXT NOT NULL,
        language TEXT NOT NULL,
        part INTEGER NOT NULL,
        parts INTEGER NOT NULL,
        post_id TEXT NOT NULL,
        built_at TEXT NOT NULL,
        published_at TEXT,
        PRIMARY KEY (anilist_id, number, language, part)
    );
    CREATE INDEX chapter_parts_by_post ON chapter_parts (post_id);
    """,
)
SCHEMA_VERSION = len(MIGRATIONS)

BUSY_TIMEOUT = 10.0  # seconds a connection waits for another connection's write lock

Rows = list[tuple]
M = TypeVar("M", bound=BaseModel)


def _statements(script: str) -> list[str]:
    """Split a migration script into single statements: `execute` runs one at a time, and
    `executescript` would commit the open transaction first."""
    statements, pending = [], ""
    for part in script.split(";"):
        pending += part + ";"
        if sqlite3.complete_statement(pending):  # False while the ';' sits inside a literal
            if pending.strip(" \t\r\n;"):
                statements.append(pending.strip())
            pending = ""
    if pending.strip(" \t\r\n;"):
        statements.append(pending.strip())  # incomplete: let SQLite report it
    return statements


def _user_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _migrate(conn: sqlite3.Connection, path: Path) -> None:
    """Bring the schema to SCHEMA_VERSION, one transaction per step. Each step takes the write
    lock first (BEGIN IMMEDIATE, waiting up to BUSY_TIMEOUT) and re-reads user_version under
    it, so when several commands open an old database at once every step runs exactly once:
    the others wait, then see the new version and move on. An up-to-date database needs no
    write lock at all (user_version only ever grows)."""
    try:
        version = _user_version(conn)
        while version < SCHEMA_VERSION:
            conn.execute("BEGIN IMMEDIATE")
            try:
                version = _user_version(conn)
                if version < SCHEMA_VERSION:
                    # the step's tables and its version bump land together, or not at all
                    for statement in _statements(MIGRATIONS[version]):
                        conn.execute(statement)
                    version += 1
                    conn.execute(f"PRAGMA user_version = {version}")
                conn.commit()
            except sqlite3.Error:
                if conn.in_transaction:
                    conn.rollback()
                raise
    except sqlite3.Error as e:
        raise StorageError(f"could not upgrade database at {path}: {e}") from e
    if version > SCHEMA_VERSION:
        raise StorageError(
            f"database at {path} has schema v{version}, newer than this manhwatok "
            f"(v{SCHEMA_VERSION}) — update manhwatok"
        )


class SqliteStore:
    """Owns the only connection to manhwatok.db. Use one per command (or per worker thread
    owner) and close it: `with SqliteStore(path) as store: ...`."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT, check_same_thread=False)
        except (sqlite3.Error, OSError) as e:
            raise StorageError(f"database at {path} is unusable: {e}") from e
        try:
            _migrate(conn, path)
            # WAL: readers don't wait for a writer, so the TUI and CLI commands can run together
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error as e:
            conn.close()
            raise StorageError(f"database at {path} is unusable: {e}") from e
        except StorageError:
            conn.close()
            raise
        self._conn = conn
        self._lock = threading.RLock()  # the connection may be shared by worker threads
        self.cache = CacheTable(self, clock)
        self.accounts = AccountTable(self)
        self.themes = ThemeTable(self)
        self.history = HistoryTable(self)
        self.chapters = ChapterTable(self)

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

    def write_many(self, error: type[ManhwatokError], sql: str, rows: list[tuple]) -> None:
        """Run one statement per row, all in a single transaction."""
        try:
            with self._lock, self._conn:
                self._conn.executemany(sql, rows)
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


class _ModelTable(Generic[M]):
    """A table of pydantic models stored as JSON under a text key."""

    TABLE: str  # SQL table
    KEY: str  # key column, also the model's key field
    MODEL: type[M]
    MISSING: type[ManhwatokError]
    NOUN: str  # for messages and the `manhwatok <noun> list` hint

    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def label(self, key: str) -> str:
        return f"{self.NOUN} {key}"

    def add(self, item: M) -> None:
        key = getattr(item, self.KEY)
        added = self._store.write(
            StorageError,
            f"INSERT INTO {self.TABLE} ({self.KEY}, data) VALUES (?, ?) "
            f"ON CONFLICT({self.KEY}) DO NOTHING",
            (key, item.model_dump_json()),
        )
        if not added:
            raise AlreadyExists(f"{self.label(key)} already exists")

    def update(self, item: M) -> None:
        key = getattr(item, self.KEY)
        changed = self._store.write(
            StorageError,
            f"UPDATE {self.TABLE} SET data = ? WHERE {self.KEY} = ?",
            (item.model_dump_json(), key),
        )
        if not changed:
            raise self._missing(key)

    def get(self, key: str) -> M:
        rows = self._store.query(
            StorageError, f"SELECT data FROM {self.TABLE} WHERE {self.KEY} = ?", (key,)
        )
        if not rows:
            raise self._missing(key)
        return self._load(key, rows[0][0])

    def list(self) -> list[M]:
        rows = self._store.query(
            StorageError, f"SELECT {self.KEY}, data FROM {self.TABLE} ORDER BY {self.KEY}"
        )
        return [self._load(key, data) for key, data in rows]

    def remove(self, key: str) -> None:
        if not self._store.write(
            StorageError, f"DELETE FROM {self.TABLE} WHERE {self.KEY} = ?", (key,)
        ):
            raise self._missing(key)

    def _missing(self, key: str) -> ManhwatokError:
        return self.MISSING(f"no {self.label(key)} — see `manhwatok {self.NOUN} list`")

    def _load(self, key: str, data: str) -> M:
        try:
            return self.MODEL.model_validate_json(data)
        except (ValidationError, ManhwatokError) as e:
            raise StorageError(f"{self.label(key)} in {self._store.path} is unreadable: {e}") from e


class AccountTable(_ModelTable[Account]):
    TABLE, KEY, MODEL, MISSING, NOUN = "accounts", "handle", Account, AccountNotFound, "account"

    def label(self, key: str) -> str:
        return f"account @{key}"


class ThemeTable(_ModelTable[Theme]):
    TABLE, KEY, MODEL, MISSING, NOUN = "themes", "name", Theme, ThemeNotFound, "theme"


def _stamp(when: datetime) -> str:
    """Fixed-width UTC ISO text, so comparing strings in SQL compares instants."""
    return when.astimezone(timezone.utc).isoformat(timespec="microseconds")


class HistoryTable:
    """Which titles each account has posted, and when: a post's first export, or a later
    upload the user confirmed."""

    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def record(
        self, account: str, post_id: str, anilist_ids: list[int], exported_at: datetime
    ) -> None:
        stamp = _stamp(exported_at)  # fixed-width UTC text, so MAX() picks the later instant
        self._store.write_many(
            StorageError,
            "INSERT INTO history (account, anilist_id, post_id, exported_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (account, anilist_id, post_id) "
            "DO UPDATE SET exported_at = MAX(exported_at, excluded.exported_at)",
            [(account, anilist_id, post_id, stamp) for anilist_id in anilist_ids],
        )

    def recent(self, account: str, since: datetime) -> set[int]:
        rows = self._store.query(
            StorageError,
            "SELECT DISTINCT anilist_id FROM history WHERE account = ? AND exported_at >= ?",
            (account, _stamp(since)),
        )
        return {anilist_id for (anilist_id,) in rows}


class ChapterTable:
    """What each title's chapters are, which were downloaded, and which parts of them were
    built into posts and published."""

    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def record_chapters(self, rows: list[ChapterRecord]) -> None:
        """Upsert what the source listed. `downloaded_at` is this machine's own fact, not the
        source's, so re-listing a chapter never clears it."""
        self._store.write_many(
            StorageError,
            "INSERT INTO chapters (anilist_id, number, language, chapter_id, manhwa_title, "
            "chapter_title, pages, downloaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL) "
            "ON CONFLICT (anilist_id, number, language) DO UPDATE SET "
            "chapter_id = excluded.chapter_id, manhwa_title = excluded.manhwa_title, "
            "chapter_title = excluded.chapter_title, pages = excluded.pages",
            [
                (
                    row.anilist_id,
                    row.number,
                    row.language,
                    row.chapter_id,
                    row.manhwa_title,
                    row.chapter_title,
                    row.pages,
                )
                for row in rows
            ],
        )

    def chapters(self, anilist_id: int, language: str = "en") -> list[ChapterRecord]:
        """Every listed chapter of the title, in chapter-number order."""
        rows = self._store.query(
            StorageError,
            "SELECT anilist_id, manhwa_title, number, chapter_id, language, chapter_title, "
            "pages, downloaded_at FROM chapters WHERE anilist_id = ? AND language = ?",
            (anilist_id, language),
        )
        found = [
            ChapterRecord(
                anilist_id=row[0],
                manhwa_title=row[1],
                number=row[2],
                chapter_id=row[3],
                language=row[4],
                chapter_title=row[5],
                pages=row[6],
                downloaded_at=datetime.fromisoformat(row[7]) if row[7] else None,
            )
            for row in rows
        ]
        return sorted(found, key=lambda c: chapter_sort_key(c.number))

    def mark_downloaded(
        self, anilist_id: int, number: str, language: str, when: datetime
    ) -> None:
        self._store.write(
            StorageError,
            "UPDATE chapters SET downloaded_at = ? "
            "WHERE anilist_id = ? AND number = ? AND language = ?",
            (_stamp(when), anilist_id, number, language),
        )

    def record_part(self, part: PartRecord) -> None:
        """Idempotent per part: rebuilding one replaces the post that carries it, and keeps the
        date it was published."""
        self._store.write(
            StorageError,
            "INSERT INTO chapter_parts (anilist_id, number, language, part, parts, post_id, "
            "built_at, published_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (anilist_id, number, language, part) DO UPDATE SET "
            "parts = excluded.parts, post_id = excluded.post_id, built_at = excluded.built_at",
            (
                part.anilist_id,
                part.number,
                part.language,
                part.part,
                part.parts,
                part.post_id,
                _stamp(part.built_at),
                _stamp(part.published_at) if part.published_at else None,
            ),
        )

    def parts(self, anilist_id: int, language: str = "en") -> list[PartRecord]:
        """Every part built of the title, in chapter then part order."""
        rows = self._store.query(
            StorageError,
            "SELECT anilist_id, number, language, part, parts, post_id, built_at, published_at "
            "FROM chapter_parts WHERE anilist_id = ? AND language = ?",
            (anilist_id, language),
        )
        found = [
            PartRecord(
                anilist_id=row[0],
                number=row[1],
                language=row[2],
                part=row[3],
                parts=row[4],
                post_id=row[5],
                built_at=datetime.fromisoformat(row[6]),
                published_at=datetime.fromisoformat(row[7]) if row[7] else None,
            )
            for row in rows
        ]
        return sorted(found, key=lambda p: (chapter_sort_key(p.number), p.part))

    def mark_published(self, post_id: str, when: datetime) -> None:
        """Stamp every part this post carries. An earlier stamp wins: the first time it went
        out is what counts, as with the export history."""
        self._store.write(
            StorageError,
            "UPDATE chapter_parts SET published_at = MIN(COALESCE(published_at, ?), ?) "
            "WHERE post_id = ?",
            (_stamp(when), _stamp(when), post_id),
        )

    def forget_parts(self, post_id: str) -> None:
        """Drop a deleted post's parts, so they are built again."""
        self._store.write(
            StorageError, "DELETE FROM chapter_parts WHERE post_id = ?", (post_id,)
        )

    def titles(self) -> list[tuple[int, str]]:
        """(anilist id, title) of every tracked title, alphabetical."""
        rows = self._store.query(
            StorageError,
            "SELECT DISTINCT anilist_id, manhwa_title FROM chapters ORDER BY manhwa_title",
        )
        return [(row[0], row[1]) for row in rows]
