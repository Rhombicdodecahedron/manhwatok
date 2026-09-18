import httpx

from manhwatok.adapters.booru import BooruSource
from tests.unit.fakes import manhwa


def _tag(name, count=10, category=3):
    return {"name": name, "post_count": count, "category": category}


def _post(post_id, score, rating="g", w=800, h=1200, artist="someone", url=None):
    return {
        "id": post_id,
        "score": score,
        "rating": rating,
        "image_width": w,
        "image_height": h,
        "tag_string_artist": artist,
        "file_url": url or f"https://cdn.test/{post_id}.jpg",
    }


class Api:
    """Scripted Danbooru: tags by name_matches, posts by tag string."""

    def __init__(self, tags=None, posts=None):
        self.tags = tags or {}
        self.posts = posts or {}
        self.calls = []

    def __call__(self, request):
        self.calls.append(request.url.path)
        if request.url.path == "/tags.json":
            wanted = request.url.params.get("search[name_matches]")
            return httpx.Response(200, json=self.tags.get(wanted, []))
        if request.url.path == "/posts.json":
            tags = request.url.params.get("tags", "")
            key = tags.split(" ")[0]
            return httpx.Response(200, json=self.posts.get(key, []))
        raise AssertionError(f"unexpected path {request.url.path}")


def _source(handler, cache=None, **kw):
    return BooruSource(
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://booru.test"),
        cache=cache,
        **kw,
    )


def test_offers_the_titles_art_best_score_first():
    api = Api(
        tags={"kubera": [_tag("kubera", 26)]},
        posts={"kubera": [_post(1, 12), _post(2, 99), _post(3, 50)]},
    )
    options = _source(api).options(manhwa(anilist_id=72579, title="Kubera"))

    assert [o.url for o in options] == [
        "https://cdn.test/2.jpg",
        "https://cdn.test/3.jpg",
        "https://cdn.test/1.jpg",
    ]


def test_ignores_a_tag_that_is_not_an_exact_match_for_the_title():
    """The live index matched '8th Class Mage' to a Gundam series; a slug match must not."""
    api = Api(
        tags={"the_return_of_the_8th_class_mage": [_tag("msv-r:_the_return_of_johnny_ridden", 30)]},
        posts={"msv-r:_the_return_of_johnny_ridden": [_post(1, 500)]},
    )
    options = _source(api).options(
        manhwa(anilist_id=136331, title="The Return of the 8th Class Mage")
    )

    assert options == []


def test_leaves_out_anything_not_rated_safe():
    api = Api(
        tags={"kubera": [_tag("kubera")]},
        posts={"kubera": [_post(1, 99, rating="e"), _post(2, 10, rating="q"), _post(3, 5)]},
    )
    options = _source(api).options(manhwa(anilist_id=72579, title="Kubera"))

    assert [o.url for o in options] == ["https://cdn.test/3.jpg"]


def test_the_label_credits_the_artist_and_shows_the_score():
    api = Api(
        tags={"kubera": [_tag("kubera")]},
        posts={"kubera": [_post(1, 42, artist="oxxo", w=900, h=1400)]},
    )
    options = _source(api).options(manhwa(anilist_id=72579, title="Kubera"))

    assert options[0].label == "★ 42  900x1400  by oxxo"


def test_a_title_the_booru_has_no_tag_for_offers_nothing():
    api = Api(tags={"doom_breaker": []})

    assert _source(api).options(manhwa(anilist_id=136220, title="Doom Breaker")) == []


def test_only_copyright_tags_count_as_the_title():
    """'I Am the Real One' matched the general tag 'gingham_clothes' live."""
    api = Api(
        tags={"i_am_the_real_one": [_tag("i_am_the_real_one", 1887, category=0)]},
        posts={"i_am_the_real_one": [_post(1, 99)]},
    )

    assert _source(api).options(manhwa(anilist_id=124783, title="I Am the Real One")) == []
