from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Manhwa, SearchQuery, Status, TagInfo
from manhwatok.domain.post import ListPost, PostItem
from manhwatok.ports.posts import SlideArt


def manhwa(**overrides) -> Manhwa:
    fields = {
        "anilist_id": 1,
        "title": "Test Manhwa",
        "romaji": "Teseuteu",
        "status": Status.RELEASING,
        "cover_url": "https://example.test/cover.jpg",
    }
    fields.update(overrides)
    return Manhwa(**fields)


class FakeMetadata:
    def __init__(self, results=(), tags=(), genres=()):
        self.results: list[Manhwa] = list(results)
        self.tags: list[TagInfo] = list(tags)
        self.genres: list[str] = list(genres)
        self.queries: list[SearchQuery] = []

    def search(self, query: SearchQuery) -> list[Manhwa]:
        self.queries.append(query)
        return list(self.results)

    def list_tags(self) -> list[TagInfo]:
        return list(self.tags)

    def list_genres(self) -> list[str]:
        return list(self.genres)


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


def post(**overrides) -> ListPost:
    items = overrides.pop("items", None)
    if items is None:
        items = [
            PostItem(manhwa=manhwa(anilist_id=i, title=f"Title {i}"), hook=f"Hook {i}")
            for i in (1, 2, 3)
        ]
    fields = {
        "id": "20260914-a3f9",
        "created_at": datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
        "title": "Manhwa where the MC *regresses*",
        "items": items,
        "candidates": [item.manhwa for item in items],
    }
    fields.update(overrides)
    return ListPost(**fields)


def cover_file(folder: Path, anilist_id: int, color=(200, 60, 60), size=(460, 650)) -> Path:
    """A real (tiny) JPEG so Pillow-based code can open it."""
    from PIL import Image

    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{anilist_id}.jpg"
    Image.new("RGB", size, color).save(path)
    return path


class FakeCovers:
    """Returns pre-made cover files; ids in `fail` raise MetadataError like a failed download.
    `on_disk`: ids already downloaded, so `cached()` returns them without fetching."""

    def __init__(
        self,
        paths: dict[int, Path] | None = None,
        fail: set[int] | None = None,
        on_disk: set[int] | None = None,
        banners: dict[int, Path] | None = None,
        fail_banners: set[int] | None = None,
    ):
        self.paths = dict(paths or {})
        self.fail = set(fail or ())
        self.on_disk = set(on_disk or ())
        self.banners = dict(banners or {})
        self.fail_banners = set(fail_banners or ())
        self.calls: list[int] = []
        self.banner_calls: list[int] = []

    def get(self, manhwa: Manhwa) -> Path:
        self.calls.append(manhwa.anilist_id)
        if manhwa.anilist_id in self.fail or manhwa.anilist_id not in self.paths:
            raise MetadataError(f"cover download failed for {manhwa.title}: HTTP 500")
        return self.paths[manhwa.anilist_id]

    def cached(self, manhwa: Manhwa) -> Path | None:
        if manhwa.anilist_id in self.on_disk and manhwa.anilist_id in self.paths:
            return self.paths[manhwa.anilist_id]
        return None

    def get_banner(self, manhwa: Manhwa) -> Path:
        self.banner_calls.append(manhwa.anilist_id)
        if manhwa.anilist_id in self.fail_banners or manhwa.anilist_id not in self.banners:
            raise MetadataError(f"banner download failed for {manhwa.title}: HTTP 500")
        return self.banners[manhwa.anilist_id]

    def cached_banner(self, manhwa: Manhwa) -> Path | None:
        if manhwa.anilist_id in self.on_disk and manhwa.anilist_id in self.banners:
            return self.banners[manhwa.anilist_id]
        return None


class FakeRenderer:
    """Writes placeholder NN.png files instead of drawing, and records what it was given."""

    def __init__(self):
        self.calls: list[tuple[ListPost, dict[int, SlideArt]]] = []

    def render(self, post: ListPost, art: dict[int, SlideArt], out_dir: Path) -> list[Path]:
        self.calls.append((post, art))
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("[0-9][0-9].png"):
            old.unlink()
        paths = [out_dir / f"{n:02d}.png" for n in range(1, post.slide_count + 1)]
        for p in paths:
            p.write_bytes(b"png")
        return paths


class ScriptedEditor:
    """Stands in for $EDITOR: `edit(text)` returns `respond(text)` and remembers what it was shown."""

    def __init__(self, respond: Callable[[str], str | None]):
        self.respond = respond
        self.shown: list[str] = []

    def __call__(self, text: str) -> str | None:
        self.shown.append(text)
        return self.respond(text)


def make_tools(tmp_path: Path, editor=None, covers=None, renderer=None, messages=None):
    """PostTools with real post folders under tmp_path and fakes for everything else."""
    from manhwatok.adapters.fs_posts import FsPostRepository
    from manhwatok.app.post_tools import PostTools

    return PostTools(
        posts=FsPostRepository(tmp_path / "posts"),
        covers=covers or FakeCovers({i: tmp_path / f"{i}.jpg" for i in (1, 2, 3, 11, 22)}),
        renderer=renderer or FakeRenderer(),
        editor=editor or ScriptedEditor(lambda text: text + "\n"),
        progress=(messages.append if messages is not None else lambda _: None),
    )


class Clock:
    """A settable time.time() stand-in for cache expiry tests."""

    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeHistory:
    """In-memory HistoryRepository: `recent()` returns `recent_ids` and records its calls."""

    def __init__(self, recent_ids=()):
        self.recent_ids = set(recent_ids)
        self.calls: list[tuple[str, datetime]] = []
        self.records: list[tuple[str, str, list[int], datetime]] = []

    def recent(self, account: str, since: datetime) -> set[int]:
        self.calls.append((account, since))
        return set(self.recent_ids)

    def record(
        self, account: str, post_id: str, anilist_ids: list[int], exported_at: datetime
    ) -> None:
        self.records.append((account, post_id, list(anilist_ids), exported_at))


class FakeUploader:
    """Stands in for the browser. Records every call in `events` (login/upload/close);
    `upload()` returns `report`; `login()` and `upload()` raise `error` if one is given."""

    def __init__(self, report=None, error: Exception | None = None):
        from manhwatok.ports.uploader import UploadReport

        self.report = report or UploadReport(attached=True, captioned=True, problems=[])
        self.error = error
        self.events: list[str] = []
        self.logins: list[str] = []
        self.uploads: list[tuple[str, list[Path], str, bool]] = []

    def login(self, handle: str) -> None:
        self.events.append("login")
        self.logins.append(handle)
        if self.error:
            raise self.error

    def upload(self, handle: str, slides: list[Path], caption: str, debug: bool):
        self.events.append("upload")
        self.uploads.append((handle, list(slides), caption, debug))
        if self.error:
            raise self.error
        return self.report

    def close(self) -> None:
        self.events.append("close")
