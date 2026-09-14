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
    visible_matches = 0
    for m in results:
        assert m.cover_url.startswith("https://")
        if any(t in m.tags for t in ("Time Manipulation", "Revenge")):
            visible_matches += 1
    # AniList's tag_in filter matches server-side on the full (spoiler-inclusive) tag set;
    # Manhwa.tags drops spoiler tags. A title can occasionally show neither queried tag if
    # AniList marks *both* isMediaSpoiler for it (confirmed live, e.g. "Kubera"), so tolerate
    # at most one such title rather than requiring every result to show a visible match.
    assert visible_matches >= 4


def test_anilist_tag_list_has_revenge():
    assert any(t.name == "Revenge" for t in AniListSource().list_tags())


def test_mangaupdates_finds_doom_breaker():
    m = Manhwa(anilist_id=0, title="Doom Breaker", romaji="", status=Status.HIATUS, start_year=2021)
    assert (MangaUpdatesSource().latest_chapter(m) or 0) >= 101
