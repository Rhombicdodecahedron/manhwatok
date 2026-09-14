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


def test_non_json_response_raises_metadata_error():
    src = _source(lambda r: httpx.Response(200, content=b"not json"))
    with pytest.raises(MetadataError, match="non-JSON"):
        src.latest_chapter(manhwa(title="X"))


def test_malformed_search_record_raises_metadata_error():
    api = Api({"X": [{"hit_title": "X", "record": None}]}, {})
    with pytest.raises(MetadataError, match="response shape changed"):
        _source(api).latest_chapter(manhwa(title="X", romaji=""))


def test_search_results_not_a_list_raises_metadata_error():
    def handler(request):
        if request.url.path == "/v1/series/search":
            return httpx.Response(200, json={"results": "not-a-list"})
        return httpx.Response(200, json={})

    with pytest.raises(MetadataError, match="response shape changed"):
        _source(handler).latest_chapter(manhwa(title="X", romaji=""))


def test_malformed_detail_body_raises_metadata_error():
    api = Api({"X": [_hit(3, "X")]}, {3: ["not", "a", "dict"]})
    with pytest.raises(MetadataError, match="response shape changed"):
        _source(api).latest_chapter(manhwa(title="X", romaji=""))


def test_empty_normalized_title_returns_none_without_request():
    api = Api({}, {})
    assert _source(api).latest_chapter(manhwa(title="!!!", romaji="")) is None
    assert api.calls == []


def test_sends_user_agent_header():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, json={"results": []})

    _source(handler).latest_chapter(manhwa(title="X", romaji=""))
    assert seen["ua"] == "manhwatok/0.1"
