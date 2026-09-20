import httpx
import pytest

from manhwatok.adapters.asura import AsuraChapters
from manhwatok.domain.errors import MetadataError
from manhwatok.ports.chapters import ChapterInfo
from tests.unit.fakes import manhwa

FALLEN = manhwa(
    anilist_id=1,
    title="Regressor of the Fallen Family",
    romaji="Mollakhan Gamunui Hoegwija",
)
IMAGE = b"RIFF fake webp"


def _series(slug, title, alts=(), chapters=0):
    return {"id": 1, "slug": slug, "title": title, "alt_titles": list(alts), "chapter_count": chapters}


def _chapter(number, slug=None, pages=26, premium=False):
    return {
        "id": 100 + number,
        "number": number,
        "slug": slug or f"uuid-{number}",
        "page_count": pages,
        "is_premium": premium,
    }


class Api:
    """Scripted asurascans API: a series search, a chapter list, one chapter and its pages."""

    def __init__(self, found=(), chapters=(), pages=2, status=200, premium=False):
        self.found = list(found)
        self.chapters = list(chapters)
        self.pages, self.status, self.premium = pages, status, premium
        self.calls: list[str] = []
        self.searched: list[str] = []

    def __call__(self, request):
        path = request.url.path
        self.calls.append(path)
        if self.status >= 400 and path.startswith("/api/series"):
            return httpx.Response(self.status)
        if path == "/api/series":
            self.searched.append(request.url.params.get("search", ""))
            return httpx.Response(200, json={"data": self.found})
        if path.endswith("/chapters"):
            return httpx.Response(200, json={"data": self.chapters})
        if "/chapters/" in path:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "chapter": {
                            "number": 1,
                            "is_premium": self.premium,
                            "pages": [
                                {"url": f"https://cdn.test/{n:03d}.webp"}
                                for n in range(1, self.pages + 1)
                            ],
                        }
                    }
                },
            )
        if request.url.host == "cdn.test":
            return httpx.Response(200, content=IMAGE)
        raise AssertionError(f"unexpected {request.url}")


def _source(tmp_path, api, **fields):
    return AsuraChapters(
        pages_dir=tmp_path / "pages",
        client=httpx.Client(
            transport=httpx.MockTransport(api), base_url="https://api.test", follow_redirects=True
        ),
        sleep=lambda _: None,
        **fields,
    )


# --- finding the series -------------------------------------------------------------------------


def test_lists_the_chapters_of_the_series_it_matched_by_name(tmp_path):
    api = Api(
        found=[_series("other", "Something Else"), _series("fallen", "Regressor of the Fallen Family")],
        chapters=[_chapter(2), _chapter(1)],
    )
    found = _source(tmp_path, api).chapters(FALLEN)
    assert [c.number for c in found] == ["1", "2"]
    assert found[0] == ChapterInfo("fallen/uuid-1", "1", "", "en", 26)


def test_a_series_is_matched_on_its_other_names_too(tmp_path):
    """Asura files Korean titles under their own romanisation."""
    api = Api(
        found=[_series("fallen", "A Flame Reborn", alts=["Mollakhan Gamunui Hoegwija"])],
        chapters=[_chapter(1)],
    )
    assert _source(tmp_path, api).chapters(FALLEN)


def test_a_title_asura_does_not_have_lists_nothing(tmp_path):
    api = Api(found=[_series("other", "Something Else")], chapters=[_chapter(1)])
    assert _source(tmp_path, api).chapters(FALLEN) == []


def test_premium_chapters_are_left_out(tmp_path):
    """Early access chapters are paid; their pages are not served."""
    api = Api(
        found=[_series("fallen", "Regressor of the Fallen Family")],
        chapters=[_chapter(1), _chapter(2, premium=True)],
    )
    assert [c.number for c in _source(tmp_path, api).chapters(FALLEN)] == ["1"]


def test_the_series_it_matched_is_remembered_not_searched_again(tmp_path):
    from tests.unit.test_mangadex import MemoryCache

    cache = MemoryCache()
    api = Api(found=[_series("fallen", "Regressor of the Fallen Family")], chapters=[_chapter(1)])
    _source(tmp_path, api, cache=cache).chapters(FALLEN)
    _source(tmp_path, api, cache=cache).chapters(FALLEN)
    assert len(api.searched) == 1


def test_a_search_failure_is_a_metadata_error_naming_the_title(tmp_path):
    with pytest.raises(MetadataError, match="Regressor of the Fallen Family"):
        _source(tmp_path, Api(status=503)).chapters(FALLEN)


def test_asura_is_one_language_so_it_offers_no_others(tmp_path):
    assert _source(tmp_path, Api()).other_languages(FALLEN, "12") == {}


# --- downloading a chapter --------------------------------------------------------------------


CHAPTER = ChapterInfo("fallen/uuid-1", "1", "", "en", 2)


def test_downloads_a_chapters_pages_in_reading_order(tmp_path):
    pages = _source(tmp_path, Api(pages=3)).pages(CHAPTER)
    assert [p.name for p in pages] == ["01.webp", "02.webp", "03.webp"]
    assert all(p.read_bytes() == IMAGE for p in pages)


def test_pages_already_on_disk_are_not_downloaded_again(tmp_path):
    api = Api()
    source = _source(tmp_path, api)
    source.pages(CHAPTER)
    before = len([c for c in api.calls if c.endswith(".webp")])
    source.pages(CHAPTER)
    assert len([c for c in api.calls if c.endswith(".webp")]) == before


def test_a_chapter_that_turns_out_to_be_premium_says_so(tmp_path):
    with pytest.raises(MetadataError, match="early access"):
        _source(tmp_path, Api(premium=True)).pages(CHAPTER)


def test_a_chapter_with_no_pages_is_a_metadata_error(tmp_path):
    with pytest.raises(MetadataError):
        _source(tmp_path, Api(pages=0)).pages(CHAPTER)


def test_cached_pages_never_downloads(tmp_path):
    api = Api()
    source = _source(tmp_path, api)
    assert source.cached_pages(CHAPTER) == []
    assert api.calls == []
    source.pages(CHAPTER)
    assert len(source.cached_pages(CHAPTER)) == 2
