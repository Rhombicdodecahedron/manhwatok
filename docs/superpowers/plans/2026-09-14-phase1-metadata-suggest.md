# Phase 1: Metadata + `suggest` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `manhwatok` CLI that suggests top Korean manhwa for given AniList tags/genres, with chapter counts (AniList, falling back to MangaUpdates for ongoing series), and lists AniList tags.

**Architecture:** Ports-and-adapters like `~/Documents/Personal/minutes`: pydantic domain models, `Protocol` ports, httpx adapters (AniList GraphQL, MangaUpdates REST), a SQLite cache decorating the chapter lookup, a use-case function, and a typer CLI wired through a lazy composition root.

**Tech Stack:** Python ≥3.12, uv (uv_build backend), httpx, pydantic v2, typer, stdlib sqlite3, pytest.

**Spec:** `docs/superpowers/specs/2026-09-14-manhwatok-design.md` (Phase 1).

## Global Constraints

- Python `>=3.12`; build backend `uv_build>=0.12.5,<0.13.0`; run everything through `uv run`.
- Runtime deps for Phase 1 exactly: `httpx>=0.27`, `pydantic>=2.7`, `typer>=0.12`. Dev: `pytest>=8.0`.
- AniList queries always filter `type: MANGA, countryOfOrigin: "KR", isAdult: false`.
- AniList `tag_in` and `genre_in` are AND filters (verified live 2026-09-14); `minimumTagRank` default 60.
- MangaUpdates search does not return `latest_chapter`; it comes from `GET /v1/series/{id}` (verified live).
- Unit tests never touch the network (use `httpx.MockTransport`). Live tests only run with `MANHWATOK_LIVE=1`.
- Data dir: `$MANHWATOK_DATA_DIR`, else `$XDG_DATA_HOME/manhwatok`, else `~/.local/share/manhwatok`. DB file: `<data_dir>/manhwatok.db`.
- Phase 1 caches only MangaUpdates chapter lookups (N calls per suggest). AniList search (1 call per suggest) is not cached — deliberate narrowing of the spec's "cache responses"; revisit if the 90 req/min limit bites.
- Phase 1 domain covers metadata only; `AccountProfile`, `ListPost`, rendering, and export belong to Phases 2–3.
- Out of scope, do not add: fetching/splitting/posting manhwa chapter pages, scraping reading sites, reposting TikToks.
- Every commit message ends with these trailer lines:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01EKMenSqSzzhkBhEk9vLfCh
  ```
- Repo root: `/home/stellaa/Documents/Personal/manhwatok`. All paths below are relative to it.

## File Structure

```
pyproject.toml, .gitignore, README.md
src/manhwatok/__init__.py
src/manhwatok/config.py                 Settings (data dir, timeouts, cache TTL)
src/manhwatok/cli.py                    typer app: suggest, tags
src/manhwatok/domain/errors.py          ManhwatokError, MetadataError
src/manhwatok/domain/models.py          Status, Manhwa, Sort, SearchQuery, TagInfo
src/manhwatok/domain/labels.py          chapter_label()
src/manhwatok/ports/metadata.py         MetadataSource, ChapterSource protocols
src/manhwatok/ports/cache.py            Cache protocol
src/manhwatok/adapters/sqlite_cache.py  SqliteCache
src/manhwatok/adapters/cached_chapters.py CachedChapterSource (decorator)
src/manhwatok/adapters/anilist.py       AniListSource, clean_description()
src/manhwatok/adapters/mangaupdates.py  MangaUpdatesSource
src/manhwatok/app/container.py          build_metadata(), build_chapter_source()
src/manhwatok/app/suggest.py            suggest_titles()
tests/unit/fakes.py                     manhwa() factory, FakeMetadata, FakeChapters
tests/unit/test_*.py                    one per module
tests/integration/test_live_apis.py     gated live checks
```
Every package dir (`domain`, `ports`, `adapters`, `app`, `tests`, `tests/unit`, `tests/integration`) gets an empty `__init__.py`.

---

### Task 1: Scaffold, config, CLI skeleton

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/manhwatok/__init__.py`, `src/manhwatok/config.py`, `src/manhwatok/cli.py`, all `__init__.py` listed above
- Test: `tests/unit/test_config.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Produces: `manhwatok.config.Settings` (dataclass: `data_dir: Path`, `http_timeout: float = 20.0`, `chapter_cache_hours: float = 24.0`, property `db_path -> Path`); `manhwatok.cli.app` (typer app), `manhwatok.cli._progress(msg: str) -> None`, `manhwatok.cli._fail(e: Exception) -> NoReturn`.

- [ ] **Step 1: Write project files**

`pyproject.toml`:
```toml
[project]
name = "manhwatok"
version = "0.1.0"
description = "Themed manhwa recommendation slideshows for TikTok accounts"
readme = "README.md"
authors = [
    { name = "Alexis Stella", email = "alexis.stella@apexlogic.com" }
]
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "pydantic>=2.7",
    "typer>=0.12",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
]

[project.scripts]
manhwatok = "manhwatok.cli:app"

[build-system]
requires = ["uv_build>=0.12.5,<0.13.0"]
build-backend = "uv_build"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`.gitignore`:
```
# Python-generated files
__pycache__/
*.py[oc]
build/
dist/
wheels/
*.egg-info

# Virtual environments
.venv

# Local secrets
.env

# Rendered exports
/out/
```

`README.md` (placeholder until Task 8):
```markdown
# manhwatok

Themed manhwa recommendation slideshows for TikTok accounts.
```

`src/manhwatok/__init__.py`, `src/manhwatok/{domain,ports,adapters,app}/__init__.py`, `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`: empty files.

- [ ] **Step 2: Write the failing tests**

`tests/unit/test_config.py`:
```python
from pathlib import Path

from manhwatok.config import Settings


def test_data_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path / "d"))
    assert Settings().data_dir == tmp_path / "d"


def test_data_dir_defaults_to_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("MANHWATOK_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert Settings().data_dir == tmp_path / "manhwatok"


def test_db_path_lives_in_data_dir():
    assert Settings(data_dir=Path("/x")).db_path == Path("/x/manhwatok.db")
```

`tests/unit/test_cli.py`:
```python
from typer.testing import CliRunner

from manhwatok.cli import app

runner = CliRunner()


def test_help_runs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "TikTok" in result.output
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv sync && uv run pytest -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'manhwatok.config'` / `'manhwatok.cli'`.

- [ ] **Step 4: Implement**

`src/manhwatok/config.py`:
```python
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    if env := os.environ.get("MANHWATOK_DATA_DIR"):
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME", "~/.local/share")
    return Path(xdg).expanduser() / "manhwatok"


@dataclass
class Settings:
    data_dir: Path = field(default_factory=_default_data_dir)
    http_timeout: float = 20.0
    chapter_cache_hours: float = 24.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "manhwatok.db"
```

`src/manhwatok/cli.py`:
```python
from __future__ import annotations

from typing import NoReturn

import typer

app = typer.Typer(
    help="Themed manhwa recommendation slideshows for TikTok.", no_args_is_help=True
)


@app.callback()
def main() -> None:
    """Themed manhwa recommendation slideshows for TikTok."""


def _progress(msg: str) -> None:
    typer.secho(f"  {msg}", fg=typer.colors.CYAN, err=True)


def _fail(e: Exception) -> NoReturn:
    typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold manhwatok package, config, CLI skeleton"
```

---

### Task 2: Domain models and chapter label

**Files:**
- Create: `src/manhwatok/domain/errors.py`, `src/manhwatok/domain/models.py`, `src/manhwatok/domain/labels.py`
- Test: `tests/unit/test_labels.py`, `tests/unit/test_models.py`

**Interfaces:**
- Produces:
  - `errors.ManhwatokError(Exception)`, `errors.MetadataError(ManhwatokError)`
  - `models.Status(StrEnum)`: `FINISHED, RELEASING, NOT_YET_RELEASED, CANCELLED, HIATUS, UNKNOWN` (values equal names)
  - `models.Manhwa(BaseModel)`: `anilist_id: int, title: str, romaji: str, status: Status, chapters: int|None=None, latest_chapter: int|None=None, start_year: int|None=None, genres: list[str]=[], tags: list[str]=[], score: int|None=None, popularity: int=0, cover_url: str="", description: str="", site_url: str=""`, property `chapter_count -> int|None`
  - `models.Sort(StrEnum)`: `SCORE="score", POPULARITY="popularity", TRENDING="trending"`
  - `models.SearchQuery(BaseModel)`: `tags: list[str]=[], genres: list[str]=[], sort: Sort=Sort.SCORE, limit: int=12 (1..50), min_tag_rank: int=60 (0..100)`
  - `models.TagInfo(BaseModel)`: `name: str, category: str, description: str=""`
  - `labels.chapter_label(m: Manhwa) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_models.py`:
```python
import pytest
from pydantic import ValidationError

from manhwatok.domain.models import Manhwa, SearchQuery, Sort, Status


def test_chapter_count_prefers_anilist_total():
    m = Manhwa(anilist_id=1, title="A", romaji="A", status=Status.FINISHED, chapters=135, latest_chapter=140)
    assert m.chapter_count == 135


def test_chapter_count_falls_back_to_latest_chapter():
    m = Manhwa(anilist_id=1, title="A", romaji="A", status=Status.RELEASING, latest_chapter=212)
    assert m.chapter_count == 212


def test_search_query_defaults():
    q = SearchQuery()
    assert (q.tags, q.genres, q.sort, q.limit, q.min_tag_rank) == ([], [], Sort.SCORE, 12, 60)


@pytest.mark.parametrize("limit", [0, 51])
def test_search_query_limit_bounds(limit):
    with pytest.raises(ValidationError):
        SearchQuery(limit=limit)
```

`tests/unit/test_labels.py`:
```python
import pytest

from manhwatok.domain.labels import chapter_label
from manhwatok.domain.models import Manhwa, Status


def _m(status, chapters=None, latest=None):
    return Manhwa(anilist_id=1, title="A", romaji="A", status=status, chapters=chapters, latest_chapter=latest)


@pytest.mark.parametrize(
    ("manhwa", "label"),
    [
        (_m(Status.FINISHED, chapters=135), "135 chapters · completed"),
        (_m(Status.FINISHED, chapters=1), "1 chapter · completed"),
        (_m(Status.CANCELLED, chapters=40), "40 chapters · cancelled"),
        (_m(Status.RELEASING, latest=212), "ongoing · ch. 212"),
        (_m(Status.HIATUS, latest=101), "hiatus · ch. 101"),
        (_m(Status.RELEASING), "ongoing"),
        (_m(Status.NOT_YET_RELEASED), "upcoming"),
        (_m(Status.UNKNOWN, chapters=40), "40 chapters"),
        (_m(Status.UNKNOWN), "chapters unknown"),
    ],
)
def test_chapter_label(manhwa, label):
    assert chapter_label(manhwa) == label
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_models.py tests/unit/test_labels.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'manhwatok.domain.models'`.

- [ ] **Step 3: Implement**

`src/manhwatok/domain/errors.py`:
```python
class ManhwatokError(Exception):
    """Base for expected, user-facing failures."""


class MetadataError(ManhwatokError):
    """A metadata source (AniList, MangaUpdates) failed or returned something unusable."""
```

`src/manhwatok/domain/models.py`:
```python
"""Core domain models. No I/O."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Status(StrEnum):
    FINISHED = "FINISHED"
    RELEASING = "RELEASING"
    NOT_YET_RELEASED = "NOT_YET_RELEASED"
    CANCELLED = "CANCELLED"
    HIATUS = "HIATUS"
    UNKNOWN = "UNKNOWN"


class Manhwa(BaseModel):
    anilist_id: int
    title: str
    romaji: str
    status: Status
    chapters: int | None = None
    latest_chapter: int | None = None
    start_year: int | None = None
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    score: int | None = None
    popularity: int = 0
    cover_url: str = ""
    description: str = ""
    site_url: str = ""

    @property
    def chapter_count(self) -> int | None:
        return self.chapters if self.chapters is not None else self.latest_chapter


class Sort(StrEnum):
    SCORE = "score"
    POPULARITY = "popularity"
    TRENDING = "trending"


class SearchQuery(BaseModel):
    tags: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    sort: Sort = Sort.SCORE
    limit: int = Field(default=12, ge=1, le=50)
    min_tag_rank: int = Field(default=60, ge=0, le=100)


class TagInfo(BaseModel):
    name: str
    category: str
    description: str = ""
```

`src/manhwatok/domain/labels.py`:
```python
from manhwatok.domain.models import Manhwa, Status

_WORD = {
    Status.FINISHED: "completed",
    Status.RELEASING: "ongoing",
    Status.HIATUS: "hiatus",
    Status.CANCELLED: "cancelled",
    Status.NOT_YET_RELEASED: "upcoming",
    Status.UNKNOWN: "",
}


def chapter_label(m: Manhwa) -> str:
    """Short slide/CLI label, e.g. '135 chapters · completed' or 'ongoing · ch. 212'."""
    word = _WORD[m.status]
    n = m.chapter_count
    if n is None:
        return word or "chapters unknown"
    count = f"{n} chapter" if n == 1 else f"{n} chapters"
    if m.status in (Status.FINISHED, Status.CANCELLED):
        return f"{count} · {word}"
    if word:
        return f"{word} · ch. {n}"
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: domain models and chapter label"
```

---

### Task 3: Ports, SQLite cache, cached chapter source

**Files:**
- Create: `src/manhwatok/ports/metadata.py`, `src/manhwatok/ports/cache.py`, `src/manhwatok/adapters/sqlite_cache.py`, `src/manhwatok/adapters/cached_chapters.py`, `tests/unit/fakes.py`
- Test: `tests/unit/test_sqlite_cache.py`, `tests/unit/test_cached_chapters.py`

**Interfaces:**
- Consumes: `Manhwa`, `SearchQuery`, `TagInfo`, `Status`, `MetadataError` (Task 2).
- Produces:
  - `ports.metadata.MetadataSource` protocol: `search(query: SearchQuery) -> list[Manhwa]`, `list_tags() -> list[TagInfo]`
  - `ports.metadata.ChapterSource` protocol: `latest_chapter(manhwa: Manhwa) -> int | None`
  - `ports.cache.Cache` protocol: `get(key: str, max_age: float) -> str | None`, `put(key: str, value: str) -> None`
  - `adapters.sqlite_cache.SqliteCache(path: Path, clock: Callable[[], float] = time.time)`
  - `adapters.cached_chapters.CachedChapterSource(inner: ChapterSource, cache: Cache, max_age: float)`; cache key `f"latest_chapter:{anilist_id}"`, value JSON (`null` cached too; exceptions not cached)
  - `tests.unit.fakes`: `manhwa(**overrides) -> Manhwa` (defaults `anilist_id=1, title="Test Manhwa", romaji="Teseuteu", status=Status.RELEASING`), `FakeMetadata(results=(), tags=())` with `.queries: list[SearchQuery]`, `FakeChapters(latest: dict[int, int|None] | None = None, error: Exception | None = None)` with `.calls: list[int]`, mutable `.latest` and `.error`

- [ ] **Step 1: Write ports and fakes**

`src/manhwatok/ports/metadata.py`:
```python
from typing import Protocol

from manhwatok.domain.models import Manhwa, SearchQuery, TagInfo


class MetadataSource(Protocol):
    def search(self, query: SearchQuery) -> list[Manhwa]: ...

    def list_tags(self) -> list[TagInfo]: ...


class ChapterSource(Protocol):
    def latest_chapter(self, manhwa: Manhwa) -> int | None: ...
```

`src/manhwatok/ports/cache.py`:
```python
from typing import Protocol


class Cache(Protocol):
    def get(self, key: str, max_age: float) -> str | None: ...

    def put(self, key: str, value: str) -> None: ...
```

`tests/unit/fakes.py`:
```python
from manhwatok.domain.models import Manhwa, SearchQuery, Status, TagInfo


def manhwa(**overrides) -> Manhwa:
    fields = {"anilist_id": 1, "title": "Test Manhwa", "romaji": "Teseuteu", "status": Status.RELEASING}
    fields.update(overrides)
    return Manhwa(**fields)


class FakeMetadata:
    def __init__(self, results=(), tags=()):
        self.results: list[Manhwa] = list(results)
        self.tags: list[TagInfo] = list(tags)
        self.queries: list[SearchQuery] = []

    def search(self, query: SearchQuery) -> list[Manhwa]:
        self.queries.append(query)
        return list(self.results)

    def list_tags(self) -> list[TagInfo]:
        return list(self.tags)


class FakeChapters:
    def __init__(self, latest: dict[int, int | None] | None = None, error: Exception | None = None):
        self.latest = dict(latest or {})
        self.error = error
        self.calls: list[int] = []

    def latest_chapter(self, manhwa: Manhwa) -> int | None:
        self.calls.append(manhwa.anilist_id)
        if self.error:
            raise self.error
        return self.latest.get(manhwa.anilist_id)
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/test_sqlite_cache.py`:
```python
from manhwatok.adapters.sqlite_cache import SqliteCache


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
```

`tests/unit/test_cached_chapters.py`:
```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sqlite_cache.py tests/unit/test_cached_chapters.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'manhwatok.adapters.sqlite_cache'`.

- [ ] **Step 4: Implement**

`src/manhwatok/adapters/sqlite_cache.py`:
```python
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
```

`src/manhwatok/adapters/cached_chapters.py`:
```python
"""Caches chapter lookups (hits and misses) so repeated suggests don't re-query MangaUpdates."""

from __future__ import annotations

import json

from manhwatok.domain.models import Manhwa
from manhwatok.ports.cache import Cache
from manhwatok.ports.metadata import ChapterSource


class CachedChapterSource:
    def __init__(self, inner: ChapterSource, cache: Cache, max_age: float) -> None:
        self._inner = inner
        self._cache = cache
        self._max_age = max_age

    def latest_chapter(self, manhwa: Manhwa) -> int | None:
        key = f"latest_chapter:{manhwa.anilist_id}"
        hit = self._cache.get(key, self._max_age)
        if hit is not None:
            return json.loads(hit)
        value = self._inner.latest_chapter(manhwa)
        self._cache.put(key, json.dumps(value))
        return value
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: ports, sqlite cache, cached chapter source"
```

---

### Task 4: AniList adapter

**Files:**
- Create: `src/manhwatok/adapters/anilist.py`
- Test: `tests/unit/test_anilist.py`

**Interfaces:**
- Consumes: `Manhwa, SearchQuery, Sort, Status, TagInfo`, `MetadataError`.
- Produces: `AniListSource(client: httpx.Client | None = None, timeout: float = 20.0)` implementing `MetadataSource`; module function `clean_description(raw: str) -> str`; constant `ANILIST_URL = "https://graphql.anilist.co"`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_anilist.py`:
```python
import json

import httpx
import pytest

from manhwatok.adapters.anilist import AniListSource, clean_description
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import SearchQuery, Sort, Status

# Shape copied from a live AniList response (2026-09-14); values trimmed.
DOOM_BREAKER = {
    "id": 125636,
    "title": {"english": "Doom Breaker", "romaji": "Pamyeol-ui Geomsa"},
    "status": "HIATUS",
    "chapters": None,
    "startDate": {"year": 2021},
    "genres": ["Action", "Fantasy"],
    "tags": [
        {"name": "Time Manipulation", "rank": 70, "isMediaSpoiler": False},
        {"name": "Revenge", "rank": 73, "isMediaSpoiler": False},
        {"name": "Tragedy", "rank": 60, "isMediaSpoiler": True},
    ],
    "averageScore": 78,
    "popularity": 21000,
    "coverImage": {"extraLarge": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/bx125636.jpg"},
    "description": "Zephyr was the last man standing.<br><br>\n(Source: Webtoon)",
    "siteUrl": "https://anilist.co/manga/125636",
}
NO_ENGLISH = {
    **DOOM_BREAKER,
    "id": 1,
    "title": {"english": None, "romaji": "Eoneu Nal"},
    "status": None,
    "chapters": 135,
}


def _page(*media):
    return {"data": {"Page": {"media": list(media)}}}


def _source(handler):
    return AniListSource(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _capture(seen):
    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_page())

    return handler


def test_search_sends_korean_filtered_query_with_only_given_filters():
    seen = {}
    _source(_capture(seen)).search(SearchQuery(tags=["Time Manipulation", "Revenge"], limit=5))
    assert 'countryOfOrigin: "KR"' in seen["query"]
    assert "isAdult: false" in seen["query"]
    assert seen["variables"] == {
        "perPage": 5,
        "sort": ["SCORE_DESC"],
        "minTagRank": 60,
        "tags": ["Time Manipulation", "Revenge"],
    }


def test_search_maps_sort_and_genres():
    seen = {}
    _source(_capture(seen)).search(SearchQuery(genres=["Action"], sort=Sort.POPULARITY))
    assert seen["variables"]["sort"] == ["POPULARITY_DESC"]
    assert seen["variables"]["genres"] == ["Action"]
    assert "tags" not in seen["variables"]


def test_search_maps_media_to_manhwa():
    [m] = _source(lambda r: httpx.Response(200, json=_page(DOOM_BREAKER))).search(
        SearchQuery(tags=["Revenge"])
    )
    assert m.anilist_id == 125636
    assert m.title == "Doom Breaker"
    assert m.romaji == "Pamyeol-ui Geomsa"
    assert m.status is Status.HIATUS
    assert m.chapters is None
    assert m.start_year == 2021
    assert m.genres == ["Action", "Fantasy"]
    assert m.tags == ["Time Manipulation", "Revenge"]  # spoiler tag dropped
    assert m.score == 78
    assert m.popularity == 21000
    assert m.cover_url.endswith("bx125636.jpg")
    assert m.description == "Zephyr was the last man standing."
    assert m.site_url == "https://anilist.co/manga/125636"


def test_search_falls_back_to_romaji_and_unknown_status():
    [m] = _source(lambda r: httpx.Response(200, json=_page(NO_ENGLISH))).search(
        SearchQuery(tags=["x"])
    )
    assert m.title == "Eoneu Nal"
    assert m.status is Status.UNKNOWN
    assert m.chapters == 135


def test_graphql_errors_raise_metadata_error():
    body = {"data": None, "errors": [{"message": "Invalid tag"}]}
    with pytest.raises(MetadataError, match="Invalid tag"):
        _source(lambda r: httpx.Response(400, json=body)).search(SearchQuery(tags=["x"]))


def test_rate_limit_raises_with_retry_hint():
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "30"}, json={})

    with pytest.raises(MetadataError, match="retry in 30s"):
        _source(handler).search(SearchQuery(tags=["x"]))


def test_network_failure_raises_metadata_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(MetadataError, match="unreachable"):
        _source(handler).search(SearchQuery(tags=["x"]))


def test_list_tags_drops_adult_tags():
    body = {
        "data": {
            "MediaTagCollection": [
                {"name": "Revenge", "category": "Theme-Drama", "description": "Revenge plot.", "isAdult": False},
                {"name": "Nudity", "category": "Sexual Content", "description": "...", "isAdult": True},
            ]
        }
    }
    tags = _source(lambda r: httpx.Response(200, json=body)).list_tags()
    assert [(t.name, t.category, t.description) for t in tags] == [
        ("Revenge", "Theme-Drama", "Revenge plot.")
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Jay's the perfect student.\n<br><br>\n(Source: WEBTOON)", "Jay's the perfect student."),
        ("First.<br><br>Second &amp; third.", "First.\nSecond & third."),
        ("<i>Note:</i>   spaced   out", "Note: spaced out"),
        ("", ""),
    ],
)
def test_clean_description(raw, expected):
    assert clean_description(raw) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_anilist.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'manhwatok.adapters.anilist'`.

- [ ] **Step 3: Implement**

`src/manhwatok/adapters/anilist.py`:
```python
"""AniList GraphQL: Korean manhwa search and the tag catalogue."""

from __future__ import annotations

import html
import re

import httpx

from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Manhwa, SearchQuery, Sort, Status, TagInfo

ANILIST_URL = "https://graphql.anilist.co"

# tag_in / genre_in are AND filters; minimumTagRank drops weak tag matches.
_SEARCH = """
query ($perPage: Int, $genres: [String], $tags: [String], $sort: [MediaSort], $minTagRank: Int) {
  Page(page: 1, perPage: $perPage) {
    media(type: MANGA, countryOfOrigin: "KR", isAdult: false,
          genre_in: $genres, tag_in: $tags, sort: $sort, minimumTagRank: $minTagRank) {
      id
      title { english romaji }
      status
      chapters
      startDate { year }
      genres
      tags { name rank isMediaSpoiler }
      averageScore
      popularity
      coverImage { extraLarge }
      description(asHtml: false)
      siteUrl
    }
  }
}
"""

_TAGS = "{ MediaTagCollection { name category description isAdult } }"

_SORT = {
    Sort.SCORE: "SCORE_DESC",
    Sort.POPULARITY: "POPULARITY_DESC",
    Sort.TRENDING: "TRENDING_DESC",
}

_SOURCE_NOTE = re.compile(r"\(\s*source:[^)]*\)", re.IGNORECASE)


def clean_description(raw: str) -> str:
    """AniList 'plain' descriptions still carry <br>/<i> tags, entities and a (Source: X) note."""
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = _SOURCE_NOTE.sub("", html.unescape(text))
    lines = (" ".join(line.split()) for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


class AniListSource:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    def search(self, query: SearchQuery) -> list[Manhwa]:
        variables: dict = {
            "perPage": query.limit,
            "sort": [_SORT[query.sort]],
            "minTagRank": query.min_tag_rank,
        }
        if query.genres:
            variables["genres"] = query.genres
        if query.tags:
            variables["tags"] = query.tags
        data = self._post(_SEARCH, variables)
        return [_to_manhwa(m) for m in data["Page"]["media"]]

    def list_tags(self) -> list[TagInfo]:
        data = self._post(_TAGS, {})
        return [
            TagInfo(name=t["name"], category=t["category"], description=t.get("description") or "")
            for t in data["MediaTagCollection"]
            if not t["isAdult"]
        ]

    def _post(self, query: str, variables: dict) -> dict:
        try:
            resp = self._client.post(
                ANILIST_URL,
                json={"query": query, "variables": variables},
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as e:
            raise MetadataError(f"AniList unreachable: {e}") from e
        if resp.status_code == 429:
            raise MetadataError(
                f"AniList rate limit hit — retry in {resp.headers.get('Retry-After', '60')}s"
            )
        try:
            body = resp.json()
        except ValueError as e:
            raise MetadataError(f"AniList returned non-JSON (HTTP {resp.status_code})") from e
        if body.get("errors"):
            raise MetadataError(
                "AniList: " + "; ".join(err.get("message", "?") for err in body["errors"])
            )
        if resp.status_code >= 400 or not body.get("data"):
            raise MetadataError(f"AniList HTTP {resp.status_code}")
        return body["data"]


def _to_manhwa(m: dict) -> Manhwa:
    title = m.get("title") or {}
    romaji = title.get("romaji") or ""
    try:
        status = Status(m.get("status"))
    except ValueError:
        status = Status.UNKNOWN
    return Manhwa(
        anilist_id=m["id"],
        title=title.get("english") or romaji,
        romaji=romaji,
        status=status,
        chapters=m.get("chapters"),
        start_year=(m.get("startDate") or {}).get("year"),
        genres=m.get("genres") or [],
        tags=[t["name"] for t in m.get("tags") or [] if not t.get("isMediaSpoiler")],
        score=m.get("averageScore"),
        popularity=m.get("popularity") or 0,
        cover_url=(m.get("coverImage") or {}).get("extraLarge") or "",
        description=clean_description(m.get("description") or ""),
        site_url=m.get("siteUrl") or "",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: AniList manhwa search and tag list"
```

---

### Task 5: MangaUpdates adapter

**Files:**
- Create: `src/manhwatok/adapters/mangaupdates.py`
- Test: `tests/unit/test_mangaupdates.py`

**Interfaces:**
- Consumes: `Manhwa`, `MetadataError`, `tests.unit.fakes.manhwa`.
- Produces: `MangaUpdatesSource(client: httpx.Client | None = None, timeout: float = 20.0)` implementing `ChapterSource`; constant `MU_API = "https://api.mangaupdates.com/v1"`.

Matching rules: try `manhwa.title`, then `manhwa.romaji` (skip empty/duplicate). For each, `POST /v1/series/search {"search": title, "perpage": 10}`; keep results whose `record.type == "Manhwa"` and whose normalized `hit_title` or `record.title` equals the normalized query (normalize = casefold, drop non-alphanumerics). Prefer a match whose `record.year == str(start_year)`, else the first match. Then `GET /v1/series/{series_id}` → `latest_chapter` if it's a positive int, else `None`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_mangaupdates.py`:
```python
import json

import httpx
import pytest

from manhwatok.adapters.mangaupdates import MangaUpdatesSource
from manhwatok.domain.errors import MetadataError
from tests.unit.fakes import manhwa


def _hit(series_id, title, type_="Manhwa", year="2021", hit_title=None):
    return {
        "hit_title": hit_title or title,
        "record": {"series_id": series_id, "title": title, "type": type_, "year": year},
    }


class Api:
    """Scripted MangaUpdates: search results keyed by search text, details keyed by series id."""

    def __init__(self, searches, details):
        self.searches = searches
        self.details = details
        self.calls = []

    def __call__(self, request):
        self.calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/v1/series/search":
            term = json.loads(request.content)["search"]
            return httpx.Response(200, json={"results": self.searches.get(term, [])})
        series_id = int(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, json=self.details[series_id])


def _source(handler):
    return MangaUpdatesSource(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_finds_series_by_title_and_returns_latest_chapter():
    api = Api(
        {"Doom Breaker": [_hit(9, "Doom Breaker"), _hit(10, "Blood Doom", type_="Manga")]},
        {9: {"latest_chapter": 101}},
    )
    assert _source(api).latest_chapter(manhwa(title="Doom Breaker", start_year=2021)) == 101
    assert api.calls == [("POST", "/v1/series/search"), ("GET", "/v1/series/9")]


def test_matches_alias_in_hit_title():
    api = Api(
        {"Balance Breaker": [_hit(5, "Real World Mobile", hit_title="Balance Breaker")]},
        {5: {"latest_chapter": 40}},
    )
    assert _source(api).latest_chapter(manhwa(title="Balance Breaker", romaji="")) == 40


def test_ignores_non_manhwa_and_non_exact_titles():
    api = Api({"Breaker": [_hit(1, "Breaker", type_="Manga"), _hit(2, "The Breaker")]}, {})
    assert _source(api).latest_chapter(manhwa(title="Breaker", romaji="")) is None
    assert all(method == "POST" for method, _ in api.calls)


def test_prefers_matching_year():
    api = Api(
        {"Tower": [_hit(1, "Tower", year="2010"), _hit(2, "Tower", year="2020")]},
        {1: {"latest_chapter": 50}, 2: {"latest_chapter": 200}},
    )
    assert _source(api).latest_chapter(manhwa(title="Tower", start_year=2020)) == 200


def test_falls_back_to_romaji_title():
    api = Api({"Pamyeol-ui Geomsa": [_hit(9, "Pamyeol-ui Geomsa")]}, {9: {"latest_chapter": 101}})
    m = manhwa(title="Doom Breaker", romaji="Pamyeol-ui Geomsa")
    assert _source(api).latest_chapter(m) == 101


def test_missing_latest_chapter_is_none():
    api = Api({"X": [_hit(3, "X")]}, {3: {"latest_chapter": None}})
    assert _source(api).latest_chapter(manhwa(title="X", romaji="")) is None


def test_http_error_raises_metadata_error():
    src = _source(lambda r: httpx.Response(500))
    with pytest.raises(MetadataError, match="HTTP 500"):
        src.latest_chapter(manhwa(title="X"))


def test_network_failure_raises_metadata_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(MetadataError, match="unreachable"):
        _source(handler).latest_chapter(manhwa(title="X"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_mangaupdates.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'manhwatok.adapters.mangaupdates'`.

- [ ] **Step 3: Implement**

`src/manhwatok/adapters/mangaupdates.py`:
```python
"""MangaUpdates: latest released chapter for series AniList has no chapter count for."""

from __future__ import annotations

import re

import httpx

from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Manhwa

MU_API = "https://api.mangaupdates.com/v1"


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", s.casefold())


class MangaUpdatesSource:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    def latest_chapter(self, manhwa: Manhwa) -> int | None:
        for title in dict.fromkeys(t for t in (manhwa.title, manhwa.romaji) if t):
            series_id = self._find(title, manhwa.start_year)
            if series_id is not None:
                return self._latest(series_id)
        return None

    def _find(self, title: str, year: int | None) -> int | None:
        body = self._request("POST", "/series/search", json={"search": title, "perpage": 10})
        want = _norm(title)
        matches = [
            r["record"]
            for r in body.get("results", [])
            if r.get("record", {}).get("type") == "Manhwa"
            and want in (_norm(r.get("hit_title") or ""), _norm(r["record"].get("title") or ""))
        ]
        if not matches:
            return None
        if year is not None:
            for record in matches:
                if record.get("year") == str(year):
                    return record["series_id"]
        return matches[0]["series_id"]

    def _latest(self, series_id: int) -> int | None:
        latest = self._request("GET", f"/series/{series_id}").get("latest_chapter")
        return latest if isinstance(latest, int) and latest > 0 else None

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = self._client.request(method, MU_API + path, **kwargs)
        except httpx.HTTPError as e:
            raise MetadataError(f"MangaUpdates unreachable: {e}") from e
        if resp.status_code >= 400:
            raise MetadataError(f"MangaUpdates HTTP {resp.status_code} for {path}")
        try:
            return resp.json()
        except ValueError as e:
            raise MetadataError(f"MangaUpdates returned non-JSON for {path}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: MangaUpdates latest-chapter lookup"
```

---

### Task 6: `suggest_titles` use case

**Files:**
- Create: `src/manhwatok/app/suggest.py`
- Test: `tests/unit/test_suggest.py`

**Interfaces:**
- Consumes: `MetadataSource`, `ChapterSource`, `SearchQuery`, `Manhwa`, `MetadataError`, fakes.
- Produces: `suggest_titles(query: SearchQuery, metadata: MetadataSource, chapters: ChapterSource | None = None, progress: Callable[[str], None] = <noop>) -> list[Manhwa]`. Order preserved; only items with `chapter_count is None` are looked up; a lookup `MetadataError` calls `progress(f"no chapter count for {m.title}: {e}")` and keeps the item. Search errors propagate.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_suggest.py`:
```python
import pytest

from manhwatok.app.suggest import suggest_titles
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import SearchQuery, Status
from tests.unit.fakes import FakeChapters, FakeMetadata, manhwa

Q = SearchQuery(tags=["Revenge"])


def test_passes_query_and_keeps_order_without_chapter_source():
    items = [manhwa(anilist_id=1, title="A"), manhwa(anilist_id=2, title="B")]
    meta = FakeMetadata(items)
    assert [m.title for m in suggest_titles(Q, meta)] == ["A", "B"]
    assert meta.queries == [Q]


def test_fills_only_missing_chapter_counts():
    finished = manhwa(anilist_id=1, status=Status.FINISHED, chapters=135)
    ongoing = manhwa(anilist_id=2, status=Status.RELEASING)
    chapters = FakeChapters({2: 212})
    out = suggest_titles(Q, FakeMetadata([finished, ongoing]), chapters)
    assert [m.chapter_count for m in out] == [135, 212]
    assert chapters.calls == [2]


def test_chapter_lookup_failure_reports_and_continues():
    msgs = []
    out = suggest_titles(
        Q,
        FakeMetadata([manhwa(title="Doom Breaker")]),
        FakeChapters(error=MetadataError("down")),
        progress=msgs.append,
    )
    assert out[0].latest_chapter is None
    assert msgs == ["no chapter count for Doom Breaker: down"]


def test_search_errors_propagate():
    class Down(FakeMetadata):
        def search(self, query):
            raise MetadataError("AniList unreachable")

    with pytest.raises(MetadataError):
        suggest_titles(Q, Down())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_suggest.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'manhwatok.app.suggest'`.

- [ ] **Step 3: Implement**

`src/manhwatok/app/suggest.py`:
```python
"""Suggest manhwa for a theme: AniList search, then fill in missing chapter counts."""

from __future__ import annotations

from typing import Callable

from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Manhwa, SearchQuery
from manhwatok.ports.metadata import ChapterSource, MetadataSource


def _noop(_: str) -> None:
    pass


def suggest_titles(
    query: SearchQuery,
    metadata: MetadataSource,
    chapters: ChapterSource | None = None,
    progress: Callable[[str], None] = _noop,
) -> list[Manhwa]:
    results = metadata.search(query)
    if chapters is None:
        return results
    enriched = []
    for m in results:
        if m.chapter_count is None:
            try:
                m = m.model_copy(update={"latest_chapter": chapters.latest_chapter(m)})
            except MetadataError as e:
                progress(f"no chapter count for {m.title}: {e}")
        enriched.append(m)
    return enriched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: suggest_titles use case with chapter backfill"
```

---

### Task 7: Composition root + `suggest` and `tags` commands

**Files:**
- Create: `src/manhwatok/app/container.py`
- Modify: `src/manhwatok/cli.py` (add imports + two commands below the existing helpers)
- Test: `tests/unit/test_cli.py` (append)

**Interfaces:**
- Consumes: `Settings`, `AniListSource`, `MangaUpdatesSource`, `CachedChapterSource`, `SqliteCache`, `suggest_titles`, `chapter_label`, `SearchQuery`, `Sort`, `ManhwatokError`, fakes.
- Produces: `container.build_metadata(settings: Settings) -> MetadataSource`, `container.build_chapter_source(settings: Settings) -> ChapterSource`. CLI commands: `manhwatok suggest [-t TAG]... [-g GENRE]... [--sort score|popularity|trending] [-n N] [--min-tag-rank R] [--chapters/--no-chapters]`, `manhwatok tags [SEARCH] [--category PREFIX]`. The CLI must call builders as `container.build_…` (module attribute) so tests can monkeypatch them.

Output format of `suggest`, one entry per result:
```
 1. Marry My Husband  [150 chapters · completed]  82%
    Drama, Romance
```
Score shows `–` when `None`. Empty result prints `no matches — try fewer tags or a lower --min-tag-rank`.
Output format of `tags`: category header line, then `  <name>` lines, sorted by (category, name). `SEARCH` matches name or description case-insensitively; `--category` is a case-insensitive prefix.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_cli.py`, add these imports to the top import block:
```python
import pytest

from manhwatok.app import container
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Status, TagInfo
from tests.unit.fakes import FakeChapters, FakeMetadata, manhwa
```
then append:
```python
@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path))


def _wire(monkeypatch, metadata, chapters=None):
    monkeypatch.setattr(container, "build_metadata", lambda settings: metadata)
    monkeypatch.setattr(
        container, "build_chapter_source", lambda settings: chapters or FakeChapters({})
    )


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert "suggest" in result.output
    assert "tags" in result.output


def test_suggest_prints_ranked_titles_with_chapter_labels(monkeypatch):
    meta = FakeMetadata(
        [
            manhwa(anilist_id=1, title="Marry My Husband", status=Status.FINISHED, chapters=150,
                   score=82, genres=["Drama", "Romance"]),
            manhwa(anilist_id=2, title="Doom Breaker", status=Status.HIATUS, score=78,
                   genres=["Action"]),
        ]
    )
    _wire(monkeypatch, meta, FakeChapters({2: 101}))
    result = runner.invoke(app, ["suggest", "-t", "Time Manipulation", "-t", "Revenge", "-n", "5"])
    assert result.exit_code == 0, result.output
    assert " 1. Marry My Husband  [150 chapters · completed]  82%" in result.output
    assert "    Drama, Romance" in result.output
    assert " 2. Doom Breaker  [hiatus · ch. 101]  78%" in result.output
    [q] = meta.queries
    assert q.tags == ["Time Manipulation", "Revenge"]
    assert q.limit == 5


def test_suggest_no_chapters_skips_mangaupdates(monkeypatch):
    _wire(monkeypatch, FakeMetadata([manhwa()]))

    def boom(settings):
        raise AssertionError("chapter source must not be built")

    monkeypatch.setattr(container, "build_chapter_source", boom)
    result = runner.invoke(app, ["suggest", "-g", "Action", "--no-chapters"])
    assert result.exit_code == 0, result.output
    assert " 1. Test Manhwa  [ongoing]  –" in result.output


def test_suggest_requires_a_filter():
    result = runner.invoke(app, ["suggest"])
    assert result.exit_code == 1
    assert "at least one --tag or --genre" in result.output


def test_suggest_reports_metadata_errors(monkeypatch):
    class Down(FakeMetadata):
        def search(self, query):
            raise MetadataError("AniList rate limit hit — retry in 30s")

    _wire(monkeypatch, Down())
    result = runner.invoke(app, ["suggest", "-t", "Revenge"])
    assert result.exit_code == 1
    assert "error: AniList rate limit hit" in result.output


def test_suggest_no_matches_hint(monkeypatch):
    _wire(monkeypatch, FakeMetadata([]))
    result = runner.invoke(app, ["suggest", "-t", "Revenge"])
    assert result.exit_code == 0
    assert "no matches" in result.output


def test_tags_grouped_by_category_and_filtered(monkeypatch):
    _wire(
        monkeypatch,
        FakeMetadata(
            tags=[
                TagInfo(name="Tragedy", category="Theme-Drama", description="Sad."),
                TagInfo(name="Time Manipulation", category="Theme-Sci-Fi", description="Loops."),
                TagInfo(name="Revenge", category="Theme-Drama", description="Revenge plot."),
            ]
        ),
    )
    result = runner.invoke(app, ["tags", "time"])
    assert result.exit_code == 0, result.output
    assert "Theme-Sci-Fi\n  Time Manipulation\n" in result.output
    assert "Revenge" not in result.output

    result = runner.invoke(app, ["tags", "--category", "theme-drama"])
    assert "Theme-Drama\n  Revenge\n  Tragedy\n" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_cli.py -q`
Expected: FAIL, `ImportError: cannot import name 'container' from 'manhwatok.app'`.

- [ ] **Step 3: Implement the composition root**

`src/manhwatok/app/container.py`:
```python
"""Composition root: builds adapters from settings. Imports adapters lazily so
`--help` stays fast."""

from __future__ import annotations

from manhwatok.config import Settings


def build_metadata(settings: Settings):
    from manhwatok.adapters.anilist import AniListSource

    return AniListSource(timeout=settings.http_timeout)


def build_chapter_source(settings: Settings):
    from manhwatok.adapters.cached_chapters import CachedChapterSource
    from manhwatok.adapters.mangaupdates import MangaUpdatesSource
    from manhwatok.adapters.sqlite_cache import SqliteCache

    return CachedChapterSource(
        MangaUpdatesSource(timeout=settings.http_timeout),
        SqliteCache(settings.db_path),
        max_age=settings.chapter_cache_hours * 3600,
    )
```

- [ ] **Step 4: Implement the commands**

In `src/manhwatok/cli.py`, replace the import block with:
```python
from __future__ import annotations

from typing import NoReturn, Optional

import typer

from manhwatok.config import Settings
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import SearchQuery, Sort
```
and append after `_fail`:
```python
@app.command()
def suggest(
    tag: Optional[list[str]] = typer.Option(
        None, "--tag", "-t", help="AniList tag; repeat to require several (see `manhwatok tags`)."
    ),
    genre: Optional[list[str]] = typer.Option(
        None, "--genre", "-g", help="AniList genre; repeat to require several."
    ),
    sort: Sort = typer.Option(Sort.SCORE, help="Ranking order."),
    limit: int = typer.Option(12, "--limit", "-n", min=1, max=50, help="How many titles."),
    min_tag_rank: int = typer.Option(
        60, min=0, max=100, help="Ignore titles where the tag is weaker than this rank."
    ),
    chapters: bool = typer.Option(
        True, "--chapters/--no-chapters", help="Look up missing chapter counts on MangaUpdates."
    ),
) -> None:
    """Suggest top Korean manhwa matching tags/genres."""
    from manhwatok.app import container
    from manhwatok.app.suggest import suggest_titles
    from manhwatok.domain.labels import chapter_label

    if not tag and not genre:
        _fail(ValueError("give at least one --tag or --genre"))
    settings = Settings()
    query = SearchQuery(
        tags=tag or [], genres=genre or [], sort=sort, limit=limit, min_tag_rank=min_tag_rank
    )
    try:
        results = suggest_titles(
            query,
            container.build_metadata(settings),
            container.build_chapter_source(settings) if chapters else None,
            progress=_progress,
        )
    except ManhwatokError as e:
        _fail(e)
    if not results:
        typer.echo("no matches — try fewer tags or a lower --min-tag-rank")
        return
    for i, m in enumerate(results, 1):
        score = f"{m.score}%" if m.score is not None else "–"
        typer.echo(f"{i:>2}. {m.title}  [{chapter_label(m)}]  {score}")
        typer.secho(f"    {', '.join(m.genres)}", dim=True)


@app.command()
def tags(
    search: Optional[str] = typer.Argument(None, help="Match tag name or description."),
    category: Optional[str] = typer.Option(None, help="Category prefix, e.g. 'Theme'."),
) -> None:
    """List AniList tags usable with `suggest --tag`."""
    from manhwatok.app import container

    try:
        items = container.build_metadata(Settings()).list_tags()
    except ManhwatokError as e:
        _fail(e)
    if search:
        s = search.casefold()
        items = [t for t in items if s in t.name.casefold() or s in t.description.casefold()]
    if category:
        c = category.casefold()
        items = [t for t in items if t.category.casefold().startswith(c)]
    current = None
    for t in sorted(items, key=lambda t: (t.category, t.name)):
        if t.category != current:
            typer.secho(t.category, bold=True)
            current = t.category
        typer.echo(f"  {t.name}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: suggest and tags CLI commands"
```

---

### Task 8: Live checks, README, end-to-end run

**Files:**
- Create: `tests/integration/test_live_apis.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `AniListSource`, `MangaUpdatesSource`, `SearchQuery`, `Manhwa`, `Status`.

- [ ] **Step 1: Write the live tests**

`tests/integration/test_live_apis.py`:
```python
"""Hit the real AniList/MangaUpdates APIs. Run with: MANHWATOK_LIVE=1 uv run pytest tests/integration"""

import os

import pytest

from manhwatok.adapters.anilist import AniListSource
from manhwatok.adapters.mangaupdates import MangaUpdatesSource
from manhwatok.domain.models import Manhwa, SearchQuery, Status

pytestmark = pytest.mark.skipif(
    os.environ.get("MANHWATOK_LIVE") != "1", reason="set MANHWATOK_LIVE=1 to hit real APIs"
)


def test_anilist_search_returns_tagged_manhwa_with_covers():
    results = AniListSource().search(SearchQuery(tags=["Time Manipulation", "Revenge"], limit=5))
    assert len(results) == 5
    for m in results:
        assert m.cover_url.startswith("https://")
        assert {"Time Manipulation", "Revenge"} <= set(m.tags)


def test_anilist_tag_list_has_revenge():
    assert any(t.name == "Revenge" for t in AniListSource().list_tags())


def test_mangaupdates_finds_doom_breaker():
    m = Manhwa(anilist_id=0, title="Doom Breaker", romaji="", status=Status.HIATUS, start_year=2021)
    assert (MangaUpdatesSource().latest_chapter(m) or 0) >= 101
```

Note on the tag assertion: spoiler tags are dropped from `Manhwa.tags`; if a result fails only because one of the two tags is a spoiler tag for that title, loosen the assertion to `any(...)` rather than changing the adapter.

- [ ] **Step 2: Run unit + live tests**

Run: `uv run pytest -q && MANHWATOK_LIVE=1 uv run pytest tests/integration -q`
Expected: unit suite all pass; live: 3 passed.

- [ ] **Step 3: End-to-end CLI run**

Run:
```bash
uv run manhwatok tags regress
uv run manhwatok suggest -t "Time Manipulation" -t Revenge -n 8
uv run manhwatok suggest -g Action -g Fantasy --sort popularity -n 5 --no-chapters
```
Expected: tag list containing the "Time Manipulation" tag; 8 numbered Korean titles each with a chapter label (ongoing ones show `ongoing · ch. N` where MangaUpdates matched); second run returns in about a second with no MangaUpdates calls. Run the first `suggest` again: it should be noticeably faster (chapter cache hit).

- [ ] **Step 4: Write README**

`README.md`:
````markdown
# manhwatok

Themed manhwa recommendation slideshows for TikTok accounts.

Phase 1: find the best Korean manhwa for a theme, with chapter counts.

## Setup

```bash
uv sync
```

## Usage

```bash
manhwatok tags regress                        # find AniList tags for a theme
manhwatok suggest -t "Time Manipulation" -t Revenge -n 10
manhwatok suggest -g Romance -g Fantasy --sort popularity
manhwatok suggest -t Murim --no-chapters      # skip MangaUpdates lookups
```

Repeated `-t`/`-g` flags must all match. `--min-tag-rank` (default 60) drops titles where a tag
is only a minor element.

Chapter counts come from AniList for finished series and from MangaUpdates (cached 24 h in
`~/.local/share/manhwatok/manhwatok.db`) for ongoing ones. Override the data dir with
`MANHWATOK_DATA_DIR`.

## Tests

```bash
uv run pytest                                        # offline unit tests
MANHWATOK_LIVE=1 uv run pytest tests/integration     # real AniList/MangaUpdates
```
````

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: live API checks; docs: README for suggest/tags"
```
