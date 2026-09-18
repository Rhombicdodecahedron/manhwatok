import json

import pytest

from manhwatok.adapters.pinterest import PinterestSource
from manhwatok.domain.errors import ManhwatokError
from tests.unit.fakes import manhwa


def _pin(url, w, h):
    return [2, {"images": {"orig": {"url": url, "width": w, "height": h}}}]


class Gallery:
    """Stands in for gallery-dl: records the argv, returns scripted JSON."""

    def __init__(self, pins=None, error=None):
        self.pins = pins if pins is not None else []
        self.error = error
        self.argv = []

    def __call__(self, argv):
        self.argv.append(argv)
        if self.error is not None:
            raise self.error
        return json.dumps(self.pins)

    @property
    def query(self) -> str:
        return next(a for a in self.argv[-1] if a.startswith("https://"))


def test_offers_the_pins_for_the_title_biggest_first():
    gallery = Gallery([
        _pin("https://i.test/small.jpg", 800, 900),
        _pin("https://i.test/big.jpg", 1500, 1600),
        _pin("https://i.test/mid.jpg", 1200, 1200),
    ])
    options = PinterestSource(run=gallery).options(manhwa(title="Kubera"))

    assert [o.url for o in options] == [
        "https://i.test/big.jpg",
        "https://i.test/mid.jpg",
        "https://i.test/small.jpg",
    ]


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


def test_the_search_names_the_title_and_the_medium():
    gallery = Gallery([])
    PinterestSource(run=gallery).options(manhwa(title="Tomb Raider King"))

    assert "Tomb+Raider+King" in gallery.query or "Tomb%20Raider%20King" in gallery.query
    assert "manhwa" in gallery.query


def test_a_tag_is_added_to_the_search():
    gallery = Gallery([])
    PinterestSource(run=gallery).options(manhwa(title="Kubera"), tag="fanart")

    assert "fanart" in gallery.query


def test_the_label_shows_the_size_since_pinterest_records_no_artist():
    gallery = Gallery([_pin("https://i.test/a.jpg", 1489, 1393)])
    options = PinterestSource(run=gallery).options(manhwa(title="Kubera"))

    assert options[0].label == "1489x1393  (no artist recorded)"


def test_a_missing_gallery_dl_says_how_to_get_it():
    gallery = Gallery(error=FileNotFoundError("gallery-dl"))

    with pytest.raises(ManhwatokError, match="gallery-dl"):
        PinterestSource(run=gallery).options(manhwa(title="Kubera"))
