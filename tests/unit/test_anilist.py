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
    "coverImage": {
        "extraLarge": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/bx125636.jpg",
        "color": "#43c9e4",
    },
    "description": "Zephyr was the last man standing.<br><br>\n(Source: Webtoon)",
    "siteUrl": "https://anilist.co/manga/125636",
}
NO_ENGLISH = {
    **DOOM_BREAKER,
    "id": 1,
    "title": {"english": None, "romaji": "Eoneu Nal"},
    "status": None,
    "chapters": 135,
    "coverImage": {"extraLarge": "https://example.test/c.jpg"},
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
    assert m.cover_color == "#43c9e4"
    assert m.description == "Zephyr was the last man standing."
    assert m.site_url == "https://anilist.co/manga/125636"


def test_search_falls_back_to_romaji_and_unknown_status():
    [m] = _source(lambda r: httpx.Response(200, json=_page(NO_ENGLISH))).search(
        SearchQuery(tags=["x"])
    )
    assert m.title == "Eoneu Nal"
    assert m.status is Status.UNKNOWN
    assert m.chapters == 135
    assert m.cover_color is None  # AniList omits color for some covers


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


def test_sends_user_agent_header():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, json=_page())

    _source(handler).search(SearchQuery(tags=["x"]))
    assert seen["ua"] == "manhwatok/0.1"


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


def test_search_sends_exclusions_only_when_given():
    seen = {}
    _source(_capture(seen)).search(
        SearchQuery(genres=["Action"], exclude_genres=["Romance"], exclude_tags=["Harem"])
    )
    assert "genre_not_in: $excludeGenres" in seen["query"]
    assert "tag_not_in: $excludeTags" in seen["query"]
    assert seen["variables"]["excludeGenres"] == ["Romance"]
    assert seen["variables"]["excludeTags"] == ["Harem"]


def test_list_genres():
    body = {"data": {"GenreCollection": ["Action", "Romance", "Slice of Life"]}}
    assert _source(lambda r: httpx.Response(200, json=body)).list_genres() == [
        "Action",
        "Romance",
        "Slice of Life",
    ]


def test_list_genres_network_failure():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(MetadataError, match="unreachable"):
        _source(handler).list_genres()
