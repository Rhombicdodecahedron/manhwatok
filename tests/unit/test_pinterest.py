import json

import pytest

from manhwatok.adapters.pinterest import PinterestSource
from manhwatok.domain.errors import ManhwatokError
from tests.unit.fakes import manhwa


def _pin(url, w, h, title="Kubera fan art", **text):
    """A pin as gallery-dl dumps it. Pins name what they show in their title by default, since
    only pins that name the manhwa are kept."""
    return [2, {"images": {"orig": {"url": url, "width": w, "height": h}}, "title": title, **text}]


class Gallery:
    """Stands in for gallery-dl: records the argv, returns scripted JSON. `more` answers any
    search after the first."""

    def __init__(self, pins=None, error=None, more=None):
        self.pins = pins if pins is not None else []
        self.more = more if more is not None else []
        self.error = error
        self.argv = []

    def __call__(self, argv):
        self.argv.append(argv)
        if self.error is not None:
            raise self.error
        return json.dumps(self.pins if len(self.argv) == 1 else self.more)

    @property
    def query(self) -> str:
        return next(a for a in self.argv[-1] if a.startswith("https://"))


def test_keeps_pinterests_own_ranking():
    """Pinterest's order is its relevance ranking, which is the only thing here that knows what
    the search meant; re-sorting it throws that away."""
    gallery = Gallery([
        _pin("https://i.test/small.jpg", 800, 900),
        _pin("https://i.test/big.jpg", 1500, 1600),
        _pin("https://i.test/mid.jpg", 1200, 1200),
    ])
    options = PinterestSource(run=gallery).options(manhwa(title="Kubera"))

    assert [o.url for o in options] == [
        "https://i.test/small.jpg",
        "https://i.test/big.jpg",
        "https://i.test/mid.jpg",
    ]


def test_each_option_carries_the_pins_size_so_it_can_be_reordered():
    gallery = Gallery([_pin("https://i.test/a.jpg", 1080, 1920)])
    options = PinterestSource(run=gallery).options(manhwa(title="Kubera"))

    assert (options[0].width, options[0].height) == (1080, 1920)


def test_the_same_pin_twice_is_offered_once():
    """Pinterest search returns each pin twice; the list must not."""
    gallery = Gallery([
        _pin("https://i.test/a.jpg", 1200, 1200),
        _pin("https://i.test/a.jpg", 1200, 1200),
        _pin("https://i.test/b.jpg", 1100, 1100),
    ])
    options = PinterestSource(run=gallery).options(manhwa(title="Kubera"))

    assert [o.url for o in options] == ["https://i.test/a.jpg", "https://i.test/b.jpg"]


def test_pins_too_small_for_a_slide_are_left_out():
    gallery = Gallery([
        _pin("https://i.test/tiny.jpg", 236, 236),
        _pin("https://i.test/ok.jpg", 1200, 1300),
    ])
    options = PinterestSource(run=gallery, min_side=600).options(manhwa(title="Kubera"))

    assert [o.url for o in options] == ["https://i.test/ok.jpg"]


def test_the_search_names_the_title_and_webtoon():
    gallery = Gallery([])
    PinterestSource(run=gallery).options(manhwa(title="Tomb Raider King"))

    assert gallery.query.endswith("?q=Tomb+Raider+King+webtoon")


def test_a_tag_replaces_webtoon_in_the_search():
    gallery = Gallery([])
    PinterestSource(run=gallery).options(manhwa(title="Kubera"), tag="fanart")

    assert gallery.query.endswith("?q=Kubera+fanart")


def test_the_label_shows_size_and_likes_since_pinterest_records_no_artist():
    gallery = Gallery([_pin("https://i.test/a.jpg", 1489, 1393, reaction_counts={"1": 42})])
    options = PinterestSource(run=gallery).options(manhwa(title="Kubera"))

    assert options[0].label == "1489x1393  42 likes  (no artist recorded)"


def test_a_missing_gallery_dl_says_how_to_get_it():
    gallery = Gallery(error=FileNotFoundError("gallery-dl"))

    with pytest.raises(ManhwatokError, match="gallery-dl"):
        PinterestSource(run=gallery).options(manhwa(title="Kubera"))


def test_an_empty_tag_searches_the_bare_title():
    gallery = Gallery([])
    PinterestSource(run=gallery).options(manhwa(title="Kubera"), tag="")

    assert gallery.query.endswith("?q=Kubera")


# --- only pins that name the manhwa --------------------------------------------------------------
# Pinterest's search is a loose text match: for "Log-in Murim manhwa fight scene" its top pins
# were Lookism and Northern Blade art. A pin says what it shows in its own text, so that decides.


def test_pins_that_do_not_name_the_manhwa_are_left_out():
    gallery = Gallery([
        _pin("https://i.test/lookism.jpg", 1080, 1920, title="Lee Jihoon vs Yook Seongji | Lookism"),
        _pin("https://i.test/blank.jpg", 1080, 1920, title=""),
        _pin("https://i.test/ok.jpg", 1080, 1920, title="Kubera ch. 3"),
    ])
    options = PinterestSource(run=gallery).options(manhwa(title="Kubera"))

    assert [o.url for o in options] == ["https://i.test/ok.jpg"]


@pytest.mark.parametrize(
    "text",
    [
        {"description": "my fav panel from #kubera"},
        {"seo_alt_text": "KUBERA - webtoon"},
        {"grid_title": "𝐊𝐮𝐛𝐞𝐫𝐚"},  # styled unicode letters, as pinners like them
        {"board": {"name": "kubera ♡"}},
        {"pin_join": {"visual_annotation": ["Kubera Webtoon", "Leez"]}},  # Pinterest's own labels
    ],
)
def test_any_of_a_pins_texts_can_name_it(text):
    gallery = Gallery([_pin("https://i.test/a.jpg", 1080, 1920, title="", **text)])
    assert PinterestSource(run=gallery).options(manhwa(title="Kubera"))


def test_a_name_must_be_whole_words():
    gallery = Gallery([_pin("https://i.test/a.jpg", 1080, 1920, title="Kuberastic edits")])
    assert PinterestSource(run=gallery).options(manhwa(title="Kubera")) == []


def test_the_romanized_name_and_alternative_titles_count():
    m = manhwa(
        title="The Legend of the Northern Blade",
        romaji="Bukgeom Jeongi",
        synonyms=["Northern Blade", "北剑江湖"],
    )
    gallery = Gallery([
        _pin("https://i.test/a.jpg", 1080, 1920, title="bukgeom jeongi"),
        _pin("https://i.test/b.jpg", 1080, 1920, title="northern blade 4k"),
        _pin("https://i.test/c.jpg", 1080, 1920, title="legend of the northern blade"),  # no "The"
    ])
    options = PinterestSource(run=gallery).options(m)

    assert len(options) == 3


def test_few_matches_search_again_under_an_alternative_title():
    """Log-in Murim is "Murim Login" on Pinterest: 0 of 50 pins under the first, 61 of 79 under
    the second."""
    m = manhwa(title="Log-in Murim", romaji="Rogeu-in Murim", synonyms=["Murim Login", "ログイン武林"])
    gallery = Gallery(
        [_pin("https://i.test/a.jpg", 1080, 1920, title="log-in murim")],
        more=[
            _pin("https://i.test/a.jpg", 1080, 1920, title="log-in murim"),
            _pin("https://i.test/b.jpg", 1080, 1920, title="Murim Login ep 12"),
        ],
    )
    options = PinterestSource(run=gallery, enough=5).options(m)

    assert gallery.argv[1][-1].endswith("?q=Murim+Login+webtoon")
    assert [o.url for o in options] == ["https://i.test/a.jpg", "https://i.test/b.jpg"]


def test_enough_matches_search_once():
    m = manhwa(title="Kubera", synonyms=["Kubera Webtoon"])
    pins = [_pin(f"https://i.test/{k}.jpg", 1080, 1920) for k in range(5)]
    gallery = Gallery(pins)
    PinterestSource(run=gallery, enough=5).options(m)

    assert len(gallery.argv) == 1


def test_titles_that_are_too_short_to_trust_are_not_matched_on():
    """A two-letter name would match half of Pinterest."""
    m = manhwa(title="Ga", romaji="Ga", synonyms=["Go"])
    gallery = Gallery([_pin("https://i.test/a.jpg", 1080, 1920, title="ga ga")])
    assert PinterestSource(run=gallery).options(m) == []


def test_each_option_carries_the_pins_likes():
    gallery = Gallery([_pin("https://i.test/a.jpg", 1080, 1920, reaction_counts={"1": 2775, "13": 1})])
    [option] = PinterestSource(run=gallery).options(manhwa(title="Kubera"))
    assert option.likes == 2776
