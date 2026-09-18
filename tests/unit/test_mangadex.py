import httpx

from manhwatok.adapters.mangadex import MangaDexSource
from tests.unit.fakes import manhwa


def _cover(cover_id, volume, file_name, locale="ja"):
    return {
        "id": cover_id,
        "attributes": {"volume": volume, "fileName": file_name, "locale": locale},
    }


class Api:
    """Scripted MangaDex: manga search results by title, covers by manga id."""

    def __init__(self, search=None, covers=None):
        self.search = search or {}
        self.covers = covers or {}
        self.calls = []

    def __call__(self, request):
        self.calls.append(request.url.path)
        if request.url.path == "/manga":
            title = request.url.params.get("title")
            return httpx.Response(200, json={"data": self.search.get(title, [])})
        if request.url.path == "/cover":
            mid = request.url.params.get("manga[]")
            return httpx.Response(200, json={"data": self.covers.get(mid, [])})
        raise AssertionError(f"unexpected path {request.url.path}")


def _source(handler, cache=None):
    return MangaDexSource(
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.test"),
        cache=cache,
    )


def test_lists_volume_covers_for_the_title_whose_anilist_link_matches():
    api = Api(
        search={
            "Doom Breaker": [
                {"id": "wrong-id", "attributes": {"links": {"al": "999"}}},
                {"id": "right-id", "attributes": {"links": {"al": "136220"}}},
            ]
        },
        covers={"right-id": [_cover("c1", "2", "two.jpg"), _cover("c2", "1", "one.jpg")]},
    )
    options = _source(api).options(manhwa(anilist_id=136220, title="Doom Breaker"))

    assert [o.label for o in options] == ["vol. 1", "vol. 2"]
    assert [o.url for o in options] == [
        "https://uploads.mangadex.org/covers/right-id/one.jpg",
        "https://uploads.mangadex.org/covers/right-id/two.jpg",
    ]


class MemoryCache:
    def __init__(self):
        self.values: dict[str, str] = {}

    def get(self, key: str, max_age: float) -> str | None:
        return self.values.get(key)

    def put(self, key: str, value: str) -> None:
        self.values[key] = value


def test_reuses_the_cached_manga_id_instead_of_searching_again():
    api = Api(
        search={"Doom Breaker": [{"id": "right-id", "attributes": {"links": {"al": "136220"}}}]},
        covers={"right-id": [_cover("c1", "1", "one.jpg")]},
    )
    cache = MemoryCache()
    title = manhwa(anilist_id=136220, title="Doom Breaker")

    _source(api, cache).options(title)
    _source(api, cache).options(title)

    assert api.calls == ["/manga", "/cover", "/cover"]


def test_falls_back_to_the_romaji_title_when_the_english_one_finds_nothing():
    api = Api(
        search={"Kubera": [{"id": "kubera-id", "attributes": {"links": {"al": "72579"}}}]},
        covers={"kubera-id": [_cover("c1", "3", "three.jpg")]},
    )
    options = _source(api).options(
        manhwa(anilist_id=72579, title="Kubera (English)", romaji="Kubera")
    )

    assert [o.label for o in options] == ["vol. 3"]


def test_no_options_when_no_result_carries_this_titles_anilist_link():
    api = Api(search={"Ghost": [{"id": "other", "attributes": {"links": {"al": "1"}}}]})

    assert _source(api).options(manhwa(anilist_id=99999, title="Ghost")) == []


def test_unnumbered_covers_sort_after_the_numbered_ones():
    api = Api(
        search={"Doom Breaker": [{"id": "m", "attributes": {"links": {"al": "136220"}}}]},
        covers={
            "m": [_cover("a", None, "none.jpg"), _cover("b", "4", "four.jpg")],
        },
    )
    options = _source(api).options(manhwa(anilist_id=136220, title="Doom Breaker"))

    assert [o.label for o in options] == ["vol. 4", "cover"]


def test_covers_of_the_same_volume_are_told_apart_by_language():
    api = Api(
        search={"Tomb Raider King": [{"id": "m", "attributes": {"links": {"al": "110462"}}}]},
        covers={
            "m": [
                _cover("a", "1", "ja.jpg", locale="ja"),
                _cover("b", "1", "en.jpg", locale="en"),
            ]
        },
    )
    options = _source(api).options(manhwa(anilist_id=110462, title="Tomb Raider King"))

    assert sorted(o.label for o in options) == ["vol. 1 (en)", "vol. 1 (ja)"]


def test_a_lone_cover_for_a_volume_keeps_the_plain_label():
    api = Api(
        search={"Doom Breaker": [{"id": "m", "attributes": {"links": {"al": "136220"}}}]},
        covers={"m": [_cover("a", "1", "only.jpg", locale="ja")]},
    )
    options = _source(api).options(manhwa(anilist_id=136220, title="Doom Breaker"))

    assert [o.label for o in options] == ["vol. 1"]
