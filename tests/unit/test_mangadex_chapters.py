import httpx
import pytest

from manhwatok.adapters.mangadex import MangaDexChapters, pick_chapters
from manhwatok.domain.errors import MetadataError
from manhwatok.ports.chapters import ChapterInfo
from tests.unit.fakes import manhwa

BOXER = manhwa(anilist_id=119174, title="The Boxer")
PAGE = b"\x89PNG fake page"


def _entry(chapter_id, number, language="en", pages=36, title="", external=None):
    return {
        "id": chapter_id,
        "attributes": {
            "chapter": number,
            "translatedLanguage": language,
            "pages": pages,
            "title": title,
            "externalUrl": external,
            "publishAt": "2026-01-01T00:00:00+00:00",
        },
    }


class Api:
    """Scripted MangaDex: a manga search, a paged chapter feed, at-home hosts and pages."""

    def __init__(self, feed=None, pages=PAGE, status=200, retry_after=None, manga="boxer-id"):
        self.feed = feed if feed is not None else []
        self.pages, self.status, self.retry_after = pages, status, retry_after
        self.manga = manga
        self.calls: list[str] = []
        self.offsets: list[int] = []
        self.rate_limited = 0

    def __call__(self, request):
        path = request.url.path
        self.calls.append(path)
        if self.retry_after is not None and path.startswith("/at-home"):
            self.rate_limited += 1
            if self.rate_limited <= 1:
                return httpx.Response(429, headers={"Retry-After": str(self.retry_after)})
        if path == "/manga":
            found = [{"id": self.manga, "attributes": {"links": {"al": "119174"}}}]
            return httpx.Response(200, json={"data": found if self.manga else []})
        if path.endswith("/feed"):
            offset = int(request.url.params.get("offset", 0))
            limit = int(request.url.params.get("limit", 100))
            self.offsets.append(offset)
            return httpx.Response(
                200, json={"data": self.feed[offset : offset + limit], "total": len(self.feed)}
            )
        if path.startswith("/at-home/server/"):
            chapter_id = path.rsplit("/", 1)[1]
            return httpx.Response(
                200,
                json={
                    "baseUrl": "https://pages.test",
                    "chapter": {"hash": "h", "data": [f"{chapter_id}-{n}.png" for n in (1, 2)]},
                },
            )
        if path.startswith("/data/"):
            if self.status >= 400:
                return httpx.Response(self.status)
            return httpx.Response(200, content=self.pages)
        raise AssertionError(f"unexpected path {path}")


def _chapters(tmp_path, api, **fields):
    slept: list[float] = []
    source = MangaDexChapters(
        pages_dir=tmp_path / "pages",
        client=httpx.Client(transport=httpx.MockTransport(api), base_url="https://api.test"),
        sleep=slept.append,
        **fields,
    )
    source.slept = slept
    return source


# --- listing chapters -------------------------------------------------------------------------


def test_lists_english_chapters_in_chapter_number_order(tmp_path):
    api = Api(feed=[_entry("b", "12"), _entry("a", "2"), _entry("c", "12.5")])
    found = _chapters(tmp_path, api).chapters(BOXER)
    assert [c.number for c in found] == ["2", "12", "12.5"]
    assert found[0] == ChapterInfo("a", "2", "", "en", 36)


def test_chapters_beyond_the_first_hundred_are_fetched_too(tmp_path):
    api = Api(feed=[_entry(f"id{n}", str(n)) for n in range(1, 251)])
    found = _chapters(tmp_path, api).chapters(BOXER)
    assert len(found) == 250
    assert api.offsets == [0, 100, 200]


def test_chapters_of_other_languages_are_left_out(tmp_path):
    api = Api(feed=[_entry("a", "1"), _entry("b", "2", language="es")])
    assert [c.number for c in _chapters(tmp_path, api).chapters(BOXER)] == ["1"]


def test_a_chapter_translated_twice_keeps_the_fuller_translation(tmp_path):
    api = Api(feed=[_entry("thin", "1", pages=4), _entry("full", "1", pages=38)])
    [found] = _chapters(tmp_path, api).chapters(BOXER)
    assert (found.chapter_id, found.pages) == ("full", 38)


def test_chapters_hosted_elsewhere_are_left_out(tmp_path):
    """An external chapter has no pages here, whatever its page count claims."""
    api = Api(feed=[_entry("a", "1"), _entry("b", "2", external="https://webtoons.test/2")])
    assert [c.number for c in _chapters(tmp_path, api).chapters(BOXER)] == ["1"]


def test_chapters_with_no_pages_are_left_out(tmp_path):
    api = Api(feed=[_entry("a", "1", pages=0), _entry("b", "2")])
    assert [c.number for c in _chapters(tmp_path, api).chapters(BOXER)] == ["2"]


def test_no_chapters_for_a_title_mangadex_does_not_have(tmp_path):
    api = Api(manga="")
    assert _chapters(tmp_path, api).chapters(BOXER) == []
    assert not any(c.endswith("/feed") for c in api.calls)


def test_the_paired_manga_id_is_read_from_the_cache_not_searched_again(tmp_path):
    from tests.unit.test_mangadex import MemoryCache

    cache = MemoryCache()
    api = Api(feed=[_entry("a", "1")])
    _chapters(tmp_path, api, cache=cache).chapters(BOXER)
    _chapters(tmp_path, api, cache=cache).chapters(BOXER)
    assert api.calls.count("/manga") == 1


def test_a_feed_failure_is_a_metadata_error_naming_the_title(tmp_path):
    class Broken(Api):
        def __call__(self, request):
            if request.url.path.endswith("/feed"):
                return httpx.Response(503)
            return super().__call__(request)

    with pytest.raises(MetadataError, match="The Boxer"):
        _chapters(tmp_path, Broken()).chapters(BOXER)


def test_pick_chapters_is_pure_and_keeps_the_sources_own_numbers():
    entries = [_entry("a", "12.5"), _entry("b", "2")]
    assert [c.number for c in pick_chapters(entries, "en")] == ["2", "12.5"]


# --- downloading pages --------------------------------------------------------------------------


CHAPTER = ChapterInfo("ch-1", "1", "", "en", 2)


def test_downloads_a_chapters_pages_in_reading_order(tmp_path):
    api = Api()
    pages = _chapters(tmp_path, api).pages(CHAPTER)
    assert [p.name for p in pages] == ["01.png", "02.png"]
    assert all(p.read_bytes() == PAGE for p in pages)
    assert pages[0].parent == tmp_path / "pages" / "ch-1"


def test_pages_already_on_disk_are_not_downloaded_again(tmp_path):
    api = Api()
    source = _chapters(tmp_path, api)
    source.pages(CHAPTER)
    before = len([c for c in api.calls if c.startswith("/data/")])
    source.pages(CHAPTER)
    assert len([c for c in api.calls if c.startswith("/data/")]) == before


def test_a_half_downloaded_page_is_fetched_again(tmp_path):
    api = Api()
    source = _chapters(tmp_path, api)
    pages = source.pages(CHAPTER)
    pages[1].write_bytes(b"")
    source.pages(CHAPTER)
    assert pages[1].read_bytes() == PAGE


def test_a_failed_page_download_leaves_no_file_behind(tmp_path):
    api = Api(status=500)
    with pytest.raises(MetadataError):
        _chapters(tmp_path, api).pages(CHAPTER)
    assert list((tmp_path / "pages" / "ch-1").glob("*")) == []


def test_a_page_bigger_than_the_cap_is_refused(tmp_path):
    api = Api(pages=b"x" * 5000)
    with pytest.raises(MetadataError, match="too big"):
        _chapters(tmp_path, api, max_page_bytes=1000).pages(CHAPTER)


def test_requests_are_spaced_so_mangadex_is_not_flooded(tmp_path):
    api = Api(feed=[_entry("a", "1")])
    source = _chapters(tmp_path, api, gap=0.25)
    source.chapters(BOXER)
    source.pages(CHAPTER)
    assert source.slept and all(0 < wait <= 0.25 for wait in source.slept)


def test_a_rate_limited_request_waits_for_the_retry_after_it_was_given(tmp_path):
    api = Api(retry_after=3)
    source = _chapters(tmp_path, api)
    source.pages(CHAPTER)
    assert 3 in source.slept


def test_a_rate_limit_that_never_lifts_gives_up_as_a_metadata_error(tmp_path):
    class Limited(Api):
        def __call__(self, request):
            if request.url.path.startswith("/at-home"):
                return httpx.Response(429, headers={"Retry-After": "600"})
            return super().__call__(request)

    with pytest.raises(MetadataError, match="rate limit"):
        _chapters(tmp_path, Limited(), max_wait=60).pages(CHAPTER)


def test_cached_pages_never_downloads(tmp_path):
    api = Api()
    source = _chapters(tmp_path, api)
    assert source.cached_pages(CHAPTER) == []
    assert api.calls == []
    source.pages(CHAPTER)
    assert [p.name for p in source.cached_pages(CHAPTER)] == ["01.png", "02.png"]


def test_progress_says_which_page_is_being_fetched(tmp_path):
    messages: list[str] = []
    _chapters(tmp_path, Api()).pages(CHAPTER, messages.append)
    assert any("1" in m and "2" in m for m in messages)
