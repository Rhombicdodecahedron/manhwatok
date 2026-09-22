import httpx
import pytest

from manhwatok.adapters.webtoons import VIEWER_REFERER, WebtoonsChapters
from manhwatok.domain.errors import MetadataError
from manhwatok.ports.chapters import ChapterInfo
from tests.unit.fakes import manhwa

BOXER = manhwa(anilist_id=119174, title="The Boxer", romaji="Bokseo")
IMAGE = b"\x89PNG fake strip"


def _card(title_no, name, genre="sports"):
    slug = name.lower().replace(" ", "-").replace("'", "")
    return (
        f'<li><a href="https://www.webtoons.com/en/{genre}/{slug}/list?title_no={title_no}"'
        f' class="link _card_item" data-title-no="{title_no}">'
        f'<div class="info_text"><strong class="title">{name}</strong></div></a></li>'
    )


def _old_card(title_no, name):
    """The markup WEBTOON used before: the name in <p class="subj">."""
    return (
        f'<li><a href="/en/x/y/list?title_no={title_no}" data-title-no="{title_no}">'
        f'<p class="subj">{name}</p></a></li>'
    )


class Site:
    """Scripted webtoons.com: a search page, the episode list API, a viewer and its images."""

    def __init__(self, cards=(), episodes=None, images=2, viewer_status=200):
        self.cards = list(cards)
        self.episodes = episodes if episodes is not None else [(1, "Ep. 1 - The Genius")]
        self.images = images
        self.viewer_status = viewer_status
        self.calls: list[str] = []
        self.referers: list[str | None] = []
        self.starts: list[int] = []

    def __call__(self, request):
        url = request.url
        self.calls.append(url.path)
        if url.path == "/en/search":
            return httpx.Response(200, text="<ul>" + "".join(self.cards) + "</ul>")
        if url.path.endswith("/episodes"):
            start = int(url.params.get("startIndex", 0))
            size = int(url.params.get("pageSize", 100))
            self.starts.append(start)
            page = self.episodes[start : start + size]
            return httpx.Response(
                200,
                json={
                    "result": {
                        "episodeList": [
                            {
                                "episodeNo": number,
                                "episodeTitle": title,
                                "viewerLink": f"/en/sports/the-boxer/ep/viewer?episode_no={number}",
                            }
                            for number, title in page
                        ]
                    }
                },
            )
        if "viewer" in url.path:
            if self.viewer_status >= 400:
                return httpx.Response(self.viewer_status)
            tags = "".join(
                f'<img src="bg.png" class="_images" data-url="https://cdn.test/p{n}.jpg">'
                for n in range(1, self.images + 1)
            )
            return httpx.Response(200, text=f"<div id='_imageList'>{tags}</div>")
        if url.host == "cdn.test":
            self.referers.append(request.headers.get("Referer"))
            return httpx.Response(200, content=IMAGE)
        raise AssertionError(f"unexpected {url}")


def _source(tmp_path, site, **fields):
    return WebtoonsChapters(
        pages_dir=tmp_path / "pages",
        client=httpx.Client(transport=httpx.MockTransport(site), follow_redirects=True),
        sleep=lambda _: None,
        **fields,
    )


# --- finding the series -------------------------------------------------------------------------


def test_lists_the_episodes_of_the_title_it_matched_by_name(tmp_path):
    site = Site(
        cards=[_card(1461, "Caster"), _card(2027, "The Boxer")],
        episodes=[(1, "Ep. 1 - The Genius"), (2, "Ep. 2 - The Omen")],
    )
    found = _source(tmp_path, site).chapters(BOXER)
    assert [c.number for c in found] == ["1", "2"]
    assert found[0] == ChapterInfo("2027:1", "1", "Ep. 1 - The Genius", "en", 0)


def test_the_older_card_markup_is_still_read(tmp_path):
    site = Site(cards=[_old_card(2027, "The Boxer")])
    assert _source(tmp_path, site).chapters(BOXER)


def test_a_title_webtoons_does_not_have_lists_nothing(tmp_path):
    site = Site(cards=[_card(1461, "Caster")])
    assert _source(tmp_path, site).chapters(BOXER) == []


def test_the_romanized_title_is_tried_too(tmp_path):
    site = Site(cards=[_card(2027, "Bokseo")])
    assert _source(tmp_path, site).chapters(BOXER)


def test_the_series_it_matched_is_remembered_not_searched_again(tmp_path):
    from tests.unit.test_mangadex import MemoryCache

    cache = MemoryCache()
    site = Site(cards=[_card(2027, "The Boxer")])
    _source(tmp_path, site, cache=cache).chapters(BOXER)
    _source(tmp_path, site, cache=cache).chapters(BOXER)
    assert site.calls.count("/en/search") == 1


def test_episodes_past_the_first_page_are_fetched_too(tmp_path):
    site = Site(
        cards=[_card(2027, "The Boxer")],
        episodes=[(n, f"Ep. {n}") for n in range(1, 251)],
    )
    found = _source(tmp_path, site, page_size=100).chapters(BOXER)
    assert len(found) == 250
    assert site.starts == [0, 100, 200]  # the short third page ends it; no wasted request


def test_a_search_failure_is_a_metadata_error_naming_the_title(tmp_path):
    class Broken(Site):
        def __call__(self, request):
            if request.url.path == "/en/search":
                return httpx.Response(503)
            return super().__call__(request)

    with pytest.raises(MetadataError, match="The Boxer"):
        _source(tmp_path, Broken()).chapters(BOXER)


# --- downloading a chapter ------------------------------------------------------------------------


CHAPTER = ChapterInfo("2027:1", "1", "Ep. 1", "en", 0)


def test_downloads_an_episodes_strips_in_reading_order(tmp_path):
    site = Site(cards=[_card(2027, "The Boxer")], images=3)
    pages = _source(tmp_path, site).pages(CHAPTER)
    assert [p.name for p in pages] == ["01.jpg", "02.jpg", "03.jpg"]
    assert all(p.read_bytes() == IMAGE for p in pages)



def test_progress_counts_strips_as_they_land(tmp_path):
    site = Site(cards=[_card(2027, "The Boxer")], images=3)
    counts = []
    _source(tmp_path, site).pages(CHAPTER, counts.append)
    assert [(c.done, c.total) for c in counts] == [(1, 3), (2, 3), (3, 3)]
    assert counts[-1] == "episode 1: strip 3 of 3"


def test_the_strips_are_asked_for_as_the_site_itself_would(tmp_path):
    """Naver's CDN answers 403 without the site as referer."""
    site = Site(cards=[_card(2027, "The Boxer")])
    _source(tmp_path, site).pages(CHAPTER)
    assert set(site.referers) == {VIEWER_REFERER}


def test_pages_already_on_disk_are_not_downloaded_again(tmp_path):
    site = Site(cards=[_card(2027, "The Boxer")])
    source = _source(tmp_path, site)
    source.pages(CHAPTER)
    before = len(site.referers)
    source.pages(CHAPTER)
    assert len(site.referers) == before


def test_an_episode_behind_fast_pass_says_so(tmp_path):
    site = Site(cards=[_card(2027, "The Boxer")], images=0)
    with pytest.raises(MetadataError, match="not free"):
        _source(tmp_path, site).pages(CHAPTER)


def test_a_viewer_that_fails_is_a_metadata_error(tmp_path):
    site = Site(cards=[_card(2027, "The Boxer")], viewer_status=500)
    with pytest.raises(MetadataError):
        _source(tmp_path, site).pages(CHAPTER)


def test_cached_pages_never_downloads(tmp_path):
    site = Site(cards=[_card(2027, "The Boxer")])
    source = _source(tmp_path, site)
    assert source.cached_pages(CHAPTER) == []
    assert site.calls == []
    source.pages(CHAPTER)
    assert len(source.cached_pages(CHAPTER)) == 2


def test_webtoons_has_one_language_so_it_offers_no_others(tmp_path):
    assert _source(tmp_path, Site()).other_languages(BOXER, "12") == {}
