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
        self.searches: list[str] = []  # the free-text lookups find() was asked for
        # What extras() answers, by id.
        self.character_urls: dict[int, list[str]] = {}
        self.synonyms: dict[int, list[str]] = {}
        self.extra_lookups: list[list[int]] = []
        self.extra_error: Exception | None = None

    def search(self, query: SearchQuery) -> list[Manhwa]:
        self.queries.append(query)
        return list(self.results)

    def find(self, text: str, limit: int = 10) -> list[Manhwa]:
        self.searches.append(text)
        return [m for m in self.results if text.lower() in m.title.lower()][:limit]

    def extras(self, ids: list[int]):
        from manhwatok.ports.metadata import TitleExtras

        self.extra_lookups.append(list(ids))
        if self.extra_error is not None:
            raise self.extra_error
        return {
            i: TitleExtras(list(self.character_urls.get(i, [])), list(self.synonyms.get(i, [])))
            for i in ids
        }

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
        characters: dict[int, Path | list[Path]] | None = None,
        fail_characters: set[int] | None = None,
    ):
        self.paths = dict(paths or {})
        self.fail = set(fail or ())
        self.on_disk = set(on_disk or ())
        self.banners = dict(banners or {})
        self.fail_banners = set(fail_banners or ())
        self.characters = dict(characters or {})
        self.fail_characters = set(fail_characters or ())
        self.calls: list[int] = []
        self.banner_calls: list[int] = []
        self.character_calls: list[int] = []

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

    def _character(self, manhwa: Manhwa, index: int) -> Path | None:
        """`characters` maps an id to its one picture, or to a list of them in order."""
        found = self.characters.get(manhwa.anilist_id)
        found = found if isinstance(found, list) else [found] if found else []
        return found[index] if index < len(found) else None

    def get_character(self, manhwa: Manhwa, index: int = 0) -> Path:
        self.character_calls.append(manhwa.anilist_id)
        path = self._character(manhwa, index)
        if manhwa.anilist_id in self.fail_characters or path is None:
            raise MetadataError(f"character download failed for {manhwa.title}: HTTP 500")
        return path

    def cached_character(self, manhwa: Manhwa, index: int = 0) -> Path | None:
        if manhwa.anilist_id in self.on_disk:
            return self._character(manhwa, index)
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

        self.report = report or UploadReport(
            attached=True, captioned=True, problems=[], titled=True
        )
        self.error = error
        self.events: list[str] = []
        self.logins: list[str] = []
        # (handle, slides, title, description, sound, debug)
        self.uploads: list[tuple[str, list[Path], str, str, str | None, bool]] = []

    def login(self, handle: str) -> None:
        self.events.append("login")
        self.logins.append(handle)
        if self.error:
            raise self.error

    def upload(self, handle, slides, title, description, sound, debug):
        self.events.append("upload")
        self.uploads.append((handle, list(slides), title, description, sound, debug))
        if self.error:
            raise self.error
        return self.report

    def close(self) -> None:
        self.events.append("close")


class FakeArtSource:
    """Scripted ArtSource: options per anilist id, and a fetch that writes a real tiny JPEG."""

    def __init__(self, options=None, error: Exception | None = None, broken=(), twins=None):
        from manhwatok.ports.art import ArtOption

        self.options_by_id: dict[int, list[ArtOption]] = dict(options or {})
        self.error = error
        self.broken: set[str] = set(broken)  # urls whose download fails
        # url -> another url whose picture it really is (a repin under a different address)
        self.twins: dict[str, str] = dict(twins or {})
        self.fetched: list[str] = []
        self.tags: list[str | None] = []  # the narrowing tag of each options() call

    def options(self, manhwa: Manhwa, tag: str | None = None):
        self.tags.append(tag)
        if self.error is not None:
            raise self.error
        return list(self.options_by_id.get(manhwa.anilist_id, []))

    def fetch(self, option, into: Path) -> Path:
        from PIL import Image

        self.fetched.append(option.url)
        if option.url in self.broken:
            from manhwatok.domain.errors import ManhwatokError

            raise ManhwatokError(f"could not download {option.url}")
        into.mkdir(parents=True, exist_ok=True)
        path = into / "picture.jpg"
        # A different picture per address, so two options are only the same file when they are
        # the same address or declared twins.
        import hashlib

        colour = hashlib.md5(self.twins.get(option.url, option.url).encode()).digest()[:3]
        Image.new("RGB", (46, 65), tuple(colour)).save(path)
        return path


def chapter_part(**overrides) -> "ChapterPart":
    from manhwatok.domain.chapter import ChapterPart

    fields = {
        "anilist_id": 1,
        "manhwa_title": "Test Manhwa",
        "number": "12",
        "chapter_id": "ch-12",
        "part": 1,
        "parts": 2,
        "panels": [f"panel-{n:03d}.png" for n in range(1, 4)],
        "pages": 36,
        "from_panel": 0,
        "to_panel": 3,
    }
    fields.update(overrides)
    return ChapterPart(**fields)


def chapter_post(**overrides) -> ListPost:
    """A post whose slides are a chapter's panels, not picks."""
    chapter = overrides.pop("chapter", None) or chapter_part()
    fields = {
        "items": [],
        "candidates": [],
        "title": f"{chapter.manhwa_title} *Chapter {chapter.number}*",
        "chapter": chapter,
    }
    fields.update(overrides)
    return post(**fields)


class FakeChapterPages:
    """Scripted chapter listings and page files, in place of MangaDex."""

    def __init__(self, chapters=None, pages=3, error=None):
        from manhwatok.ports.chapters import ChapterInfo

        self.listed: list[ChapterInfo] = list(chapters or [])
        self.pages_each = pages
        self.error = error
        self.listings: list[int] = []  # anilist ids chapters() was asked about
        self.downloads: list[str] = []  # chapter ids pages() was asked for
        self.root: Path | None = None  # set by make_chapter_tools

    def chapters(self, manhwa: Manhwa, language: str = "en"):
        self.listings.append(manhwa.anilist_id)
        if self.error is not None:
            raise self.error
        return [c for c in self.listed if c.language == language]

    def pages(self, chapter, progress=None) -> list[Path]:
        self.downloads.append(chapter.chapter_id)
        folder = (self.root or Path(".")) / "pages" / chapter.chapter_id
        folder.mkdir(parents=True, exist_ok=True)
        made = []
        for n in range(1, self.pages_each + 1):
            path = folder / f"{n:02d}.png"
            if not path.is_file():
                cover_file(folder, n, color=(40, 40, 40), size=(20, 40))
                (folder / f"{n}.jpg").replace(path)
            made.append(path)
        if progress:
            progress(f"chapter {chapter.number}: {len(made)} pages")
        return made

    def cached_pages(self, chapter) -> list[Path]:
        folder = (self.root or Path(".")) / "pages" / chapter.chapter_id
        return sorted(folder.glob("[0-9][0-9].png"))

    def close(self) -> None:
        """Nothing to close; the real source has an HTTP client."""


class FakeCutter:
    """Cuts every chapter into `panels` slide-sized pictures, one colour each."""

    def __init__(self, panels=4):
        self.panels = panels
        self.cuts: list[Path] = []  # the folders it was asked to cut into

    def cut(self, pages: list[Path], out_dir: Path, prefix: str = "panel") -> list[Path]:
        from PIL import Image

        found = sorted(out_dir.glob(f"{prefix}-*.png"))
        if len(found) == self.panels:
            return found
        self.cuts.append(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        made = []
        for n in range(1, self.panels + 1):
            path = out_dir / f"{prefix}-{n:03d}.png"
            Image.new("RGB", (1080, 1920), (20 * n % 255, 60, 120)).save(path)
            made.append(path)
        return made


class FakeChapterRepo:
    """In-memory ChapterRepository."""

    def __init__(self):
        self.rows: dict[tuple, object] = {}
        self.built: dict[tuple, object] = {}

    def record_chapters(self, rows) -> None:
        for row in rows:
            key = (row.anilist_id, row.number, row.language)
            kept = self.rows.get(key)
            downloaded = kept.downloaded_at if kept else None
            self.rows[key] = row.model_copy(update={"downloaded_at": downloaded})

    def chapters(self, anilist_id: int, language: str = "en"):
        from manhwatok.domain.chapter import chapter_sort_key

        found = [
            row
            for (aid, _, lang), row in self.rows.items()
            if aid == anilist_id and lang == language
        ]
        return sorted(found, key=lambda c: chapter_sort_key(c.number))

    def mark_downloaded(self, anilist_id, number, language, when) -> None:
        key = (anilist_id, number, language)
        if key in self.rows:
            self.rows[key] = self.rows[key].model_copy(update={"downloaded_at": when})

    def record_part(self, part) -> None:
        self.built[(part.anilist_id, part.number, part.language, part.part)] = part

    def parts(self, anilist_id: int, language: str = "en"):
        from manhwatok.domain.chapter import chapter_sort_key

        found = [p for p in self.built.values() if p.anilist_id == anilist_id and p.language == language]
        return sorted(found, key=lambda p: (chapter_sort_key(p.number), p.part))

    def mark_published(self, post_id: str, when) -> None:
        for key, part in self.built.items():
            if part.post_id == post_id and part.published_at is None:
                self.built[key] = part.model_copy(update={"published_at": when})

    def forget_parts(self, post_id: str) -> None:
        self.built = {k: p for k, p in self.built.items() if p.post_id != post_id}

    def titles(self) -> list[tuple[int, str]]:
        seen = {row.anilist_id: row.manhwa_title for row in self.rows.values()}
        return sorted(seen.items(), key=lambda pair: pair[1])


def make_chapter_tools(tmp_path: Path, pages=None, cutter=None, chapters=None):
    """ChapterTools with fakes and a pages folder under tmp_path."""
    from manhwatok.app.chapter_post import ChapterTools

    pages = pages or FakeChapterPages()
    pages.root = tmp_path
    return ChapterTools(
        pages=pages,
        cutter=cutter or FakeCutter(),
        chapters=chapters or FakeChapterRepo(),
        pages_dir=tmp_path / "pages",
    )
