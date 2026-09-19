import httpx
import pytest

from manhwatok.adapters.reddit import RedditSource
from manhwatok.domain.errors import ManhwatokError, MetadataError
from tests.unit.fakes import Clock, manhwa


def _image(post_id, score, sub="sololeveling", w=1080, h=1920, **extra):
    return {
        "kind": "t3",
        "data": {
            "id": post_id,
            "score": score,
            "subreddit": sub,
            "over_18": False,
            "post_hint": "image",
            "url": f"https://i.redd.it/{post_id}.jpg",
            "preview": {"images": [{"source": {"url": "https://preview.test/x", "width": w,
                                               "height": h}}]},
            **extra,
        },
    }


def _gallery(post_id, score, pictures, sub="manhwa"):
    """`pictures`: (media id, mime, width, height), in the order the gallery shows them."""
    return {
        "kind": "t3",
        "data": {
            "id": post_id,
            "score": score,
            "subreddit": sub,
            "over_18": False,
            "is_gallery": True,
            "url": f"https://www.reddit.com/gallery/{post_id}",
            "gallery_data": {"items": [{"media_id": m} for m, _, _, _ in pictures]},
            "media_metadata": {
                m: {"status": "valid", "e": "Image", "m": mime,
                    "s": {"u": f"https://preview.redd.it/{m}", "x": w, "y": h}}
                for m, mime, w, h in pictures
            },
        },
    }


def _text(post_id, score):
    return {"kind": "t3", "data": {"id": post_id, "score": score, "subreddit": "manhwa",
                                   "over_18": False, "is_self": True,
                                   "url": f"https://www.reddit.com/r/manhwa/{post_id}"}}


class Api:
    """Scripted Reddit: an OAuth token endpoint and a search listing."""

    def __init__(self, posts=(), token_status=200, search_status=200, expires_in=3600):
        self.posts = list(posts)
        self.token_status = token_status
        self.search_status = search_status
        self.expires_in = expires_in
        self.token_calls = 0
        self.searches: list[httpx.Request] = []

    def __call__(self, request):
        if request.url.path == "/api/v1/access_token":
            self.token_calls += 1
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(
                200, json={"access_token": f"tok{self.token_calls}", "token_type": "bearer",
                           "expires_in": self.expires_in}
            )
        if request.url.path == "/search":
            self.searches.append(request)
            if self.search_status != 200:
                return httpx.Response(self.search_status)
            return httpx.Response(200, json={"kind": "Listing",
                                             "data": {"children": self.posts}})
        raise AssertionError(f"unexpected path {request.url.path}")


def _source(api, clock=None, **kw):
    creds = {"client_id": "id", "client_secret": "secret", "user": "someone"} | kw
    return RedditSource(
        client=httpx.Client(transport=httpx.MockTransport(api)), clock=clock or Clock(), **creds
    )


SOLO = manhwa(anilist_id=105398, title="Solo Leveling")


def test_offers_image_posts_in_reddits_top_voted_order():
    api = Api([_image("a", 5400), _image("b", 1200)])

    options = _source(api).options(SOLO)

    assert [o.url for o in options] == ["https://i.redd.it/a.jpg", "https://i.redd.it/b.jpg"]
    assert (options[0].width, options[0].height) == (1080, 1920)


def test_each_option_shows_its_votes_and_where_it_was_posted():
    options = _source(Api([_image("a", 5400, sub="sololeveling")])).options(SOLO)

    assert "5400" in options[0].label and "r/sololeveling" in options[0].label


def test_searches_the_quoted_title_for_panels_top_voted_of_all_time():
    api = Api()

    _source(api).options(SOLO)

    params = api.searches[0].url.params
    assert params["q"] == '"Solo Leveling" panel'
    assert (params["sort"], params["t"], params["type"]) == ("top", "all", "link")


def test_a_tag_replaces_the_default_words():
    api = Api()
    source = _source(api)

    source.options(SOLO, "fight scene")
    source.options(SOLO, "")

    assert [r.url.params["q"] for r in api.searches] == [
        '"Solo Leveling" fight scene',
        '"Solo Leveling"',
    ]


def test_offers_every_picture_of_a_gallery_in_the_galleries_order():
    api = Api([_gallery("g", 900, [("m2", "image/png", 1080, 1920),
                                   ("m1", "image/jpg", 1200, 1800)])])

    options = _source(api).options(SOLO)

    assert [o.url for o in options] == ["https://i.redd.it/m2.png", "https://i.redd.it/m1.jpg"]
    assert "1/2" in options[0].label and "2/2" in options[1].label


def test_skips_nsfw_posts():
    api = Api([_image("a", 900, over_18=True), _image("b", 100)])

    assert [o.url for o in _source(api).options(SOLO)] == ["https://i.redd.it/b.jpg"]


def test_skips_posts_that_are_not_pictures():
    api = Api([_text("t", 9000), _image("b", 100)])

    assert [o.url for o in _source(api).options(SOLO)] == ["https://i.redd.it/b.jpg"]


def test_skips_pictures_too_small_for_a_slide():
    api = Api([_image("thumb", 900, w=320, h=480), _image("b", 100)])

    assert [o.url for o in _source(api).options(SOLO)] == ["https://i.redd.it/b.jpg"]


def test_a_picture_crossposted_twice_is_offered_once():
    api = Api([_image("a", 900), _image("a", 100, sub="manhwa")])

    assert len(_source(api).options(SOLO)) == 1


def test_asks_for_a_token_once_and_sends_it_with_every_search():
    api = Api()
    source = _source(api)

    source.options(SOLO)
    source.options(SOLO)

    assert api.token_calls == 1
    assert all(r.headers["Authorization"] == "bearer tok1" for r in api.searches)


def test_asks_for_a_new_token_once_the_old_one_expires():
    api = Api(expires_in=3600)
    clock = Clock()
    source = _source(api, clock)

    source.options(SOLO)
    clock.now += 3600
    source.options(SOLO)

    assert api.token_calls == 2
    assert api.searches[-1].headers["Authorization"] == "bearer tok2"


def test_identifies_itself_the_way_reddit_asks():
    api = Api()

    _source(api, user="someone").options(SOLO)

    assert api.searches[0].headers["User-Agent"] == "linux:manhwatok:0.1 (by /u/someone)"


def test_refused_credentials_say_so():
    with pytest.raises(ManhwatokError, match="refused"):
        _source(Api(token_status=401)).options(SOLO)


def test_a_failed_search_is_a_metadata_error():
    with pytest.raises(MetadataError, match="503"):
        _source(Api(search_status=503)).options(SOLO)


# --- without keys: Reddit's public search feed ------------------------------------------------


def _entry(thing_id, sub="", title="A panel", link=""):
    category = f'<category term="{sub}" label="r/{sub}"/>' if sub else ""
    content = f'&lt;a href="{link}"&gt;[link]&lt;/a&gt;' if link else "&lt;div&gt;text&lt;/div&gt;"
    return (f"<entry><id>{thing_id}</id>{category}<title>{title}</title>"
            f'<content type="html">{content}</content></entry>')


def _feed(*entries):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:media="http://search.yahoo.com/mrss/">' + "".join(entries) + "</feed>")


class Feed:
    """Scripted search.rss: answers in turn from `replies` (status, headers), the last repeating."""

    def __init__(self, body="", replies=((200, {}),)):
        self.body = body
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        assert request.url.path == "/search.rss", request.url.path
        self.requests.append(request)
        status, headers = self.replies[min(len(self.requests), len(self.replies)) - 1]
        text = self.body if status == 200 else ""
        return httpx.Response(status, headers=headers, text=text)


def _keyless(feed, clock=None, slept=None, **kw):
    clock = clock or Clock()
    slept = slept if slept is not None else []

    def sleep(seconds):
        slept.append(seconds)
        clock.now += seconds

    return RedditSource(
        "", "", client=httpx.Client(transport=httpx.MockTransport(feed)), clock=clock,
        sleep=sleep, **kw,
    )


PANELS = _feed(
    _entry("t5_r7x8p", title="Solo Leveling"),  # a subreddit, not a post
    _entry("t3_a", "sololeveling", "Hardest panel", "https://i.redd.it/a.png"),
    _entry("t3_g", "manhwa", "Favourite panels?", "https://www.reddit.com/gallery/g"),
    _entry("t3_t", "sololeveling", "Discussion"),
    _entry("t3_i", "manga", "My fav panel", "https://i.imgur.com/i.png"),
    _entry("t3_b", "sololeveling", "Cold panel", "https://i.redd.it/b.jpeg"),
)


def test_without_keys_reads_reddits_search_feed_in_its_top_voted_order():
    options = _keyless(Feed(PANELS)).options(SOLO)

    assert [o.url for o in options] == [
        "https://i.redd.it/a.png",
        "https://i.imgur.com/i.png",
        "https://i.redd.it/b.jpeg",
    ]


def test_the_feed_is_searched_for_the_quoted_title_top_voted_of_all_time():
    feed = Feed(PANELS)

    _keyless(feed).options(SOLO, "best panel")

    params = feed.requests[0].url.params
    assert params["q"] == '"Solo Leveling" best panel'
    assert (params["sort"], params["t"]) == ("top", "all")
    assert feed.requests[0].url.host == "www.reddit.com"


def test_feed_options_show_their_rank_and_subreddit():
    options = _keyless(Feed(PANELS)).options(SOLO)

    assert options[0].label.startswith("top #1  r/sololeveling")
    assert options[2].label.startswith("top #3  r/sololeveling")


def test_feed_options_have_no_size_since_the_feed_gives_none():
    """Unmeasured, so --order portrait/size put them after measured ones rather than guessing."""
    option = _keyless(Feed(PANELS)).options(SOLO)[0]

    assert (option.width, option.height) == (0, 0)


def test_the_feed_is_asked_again_only_once_reddits_window_has_reset():
    """Reddit allows one request, then says how long until the next: that wait is kept."""
    feed = Feed(PANELS, [(200, {"x-ratelimit-remaining": "0.0", "x-ratelimit-reset": "25"})])
    slept = []
    source = _keyless(feed, slept=slept)

    source.options(SOLO)
    source.options(SOLO)

    assert sum(slept) >= 25
    assert len(feed.requests) == 2


def test_a_rate_limited_search_waits_as_long_as_reddit_asks_then_retries():
    feed = Feed(PANELS, [(429, {"retry-after": "40"}), (200, {})])
    slept = []

    options = _keyless(feed, slept=slept).options(SOLO)

    assert len(options) == 3
    assert 40 in slept


def test_a_search_still_limited_after_waiting_stops_with_a_clear_error():
    feed = Feed(PANELS, [(429, {"retry-after": "40"})])

    with pytest.raises(MetadataError, match="too many requests"):
        _keyless(feed).options(SOLO)
    assert len(feed.requests) == 2


def test_an_unreadable_feed_is_a_metadata_error():
    with pytest.raises(MetadataError, match="feed"):
        _keyless(Feed("<not xml")).options(SOLO)


def test_with_keys_the_api_is_used_instead_of_the_feed():
    api = Api([_image("a", 10)])

    _source(api).options(SOLO)

    assert api.token_calls == 1 and len(api.searches) == 1


def test_the_feed_is_asked_plainly_the_way_reddit_answers_it():
    """Measured: Reddit answers 403 to the feed request with httpx's default compression
    header, and 200 to a plain one naming this tool."""
    feed = Feed(PANELS)

    _keyless(feed).options(SOLO)

    headers = feed.requests[0].headers
    assert headers["Accept-Encoding"] == "identity"
    assert headers["User-Agent"].startswith("linux:manhwatok:")


def test_feed_searches_are_spaced_a_minute_apart_even_unasked():
    """Two searches 30s apart got a 429; 75s apart never did."""
    slept = []
    source = _keyless(Feed(PANELS), slept=slept)

    source.options(SOLO)
    source.options(SOLO)

    assert sum(slept) >= 60
