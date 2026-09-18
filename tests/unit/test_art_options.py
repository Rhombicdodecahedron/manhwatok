import pytest

from manhwatok.app.art_options import list_art, use_art
from manhwatok.domain.models import ArtOrder
from manhwatok.domain.errors import ManhwatokError
from manhwatok.ports.art import ArtOption
from tests.unit.fakes import FakeArtSource, make_tools, post

VOL1 = ArtOption(label="vol. 1", url="https://example.test/one.jpg")
VOL2 = ArtOption(label="vol. 2", url="https://example.test/two.jpg")


def _saved(tmp_path, tools):
    p = post()
    tools.posts.save(p)
    return p


def test_lists_the_sources_options_for_one_title_of_the_post(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    source = FakeArtSource({2: [VOL1, VOL2]})

    assert list_art("20260914-a3f9", 2, tools, source) == [VOL1, VOL2]


def test_listing_a_title_the_post_does_not_have_is_an_error(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)

    with pytest.raises(ManhwatokError, match="no title 999"):
        list_art("20260914-a3f9", 999, tools, FakeArtSource())


def test_using_an_option_downloads_it_and_records_it_as_that_titles_art(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    source = FakeArtSource({2: [VOL1, VOL2]})

    kept = use_art("20260914-a3f9", 2, VOL2, tools, source)

    assert source.fetched == [VOL2.url]
    assert kept.is_file()
    saved = tools.posts.get("20260914-a3f9")
    assert saved.items[1].custom_art == kept.name
    assert kept.parent == tools.posts.folder("20260914-a3f9")


def test_the_downloaded_file_does_not_linger_outside_the_post_folder(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)

    use_art("20260914-a3f9", 2, VOL1, tools, FakeArtSource({2: [VOL1]}))

    folder = tools.posts.folder("20260914-a3f9")
    assert [p.name for p in folder.glob("picture*")] == []


WIDE = ArtOption("wide", "https://x.test/wide.jpg", width=1600, height=900)
TALL = ArtOption("tall", "https://x.test/tall.jpg", width=1080, height=1920)
HUGE = ArtOption("huge", "https://x.test/huge.jpg", width=2400, height=2400)


def test_the_sources_own_order_is_kept_by_default(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    source = FakeArtSource({2: [WIDE, TALL, HUGE]})

    assert list_art("20260914-a3f9", 2, tools, source) == [WIDE, TALL, HUGE]


def test_ordering_by_size_puts_the_biggest_first(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    source = FakeArtSource({2: [WIDE, TALL, HUGE]})

    got = list_art("20260914-a3f9", 2, tools, source, order=ArtOrder.SIZE)

    assert [o.label for o in got] == ["huge", "tall", "wide"]


def test_ordering_by_portrait_puts_the_most_slide_shaped_first(tmp_path):
    """A slide is 1080x1920, so 9:16 wins, a square is next and a landscape picture is last."""
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    source = FakeArtSource({2: [WIDE, HUGE, TALL]})

    got = list_art("20260914-a3f9", 2, tools, source, order=ArtOrder.PORTRAIT)

    assert [o.label for o in got] == ["tall", "huge", "wide"]


def test_options_without_a_size_keep_their_place_when_ordering_by_size(tmp_path):
    """MangaDex reports no dimensions; ordering must not throw them away."""
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    sizeless = ArtOption("vol. 1", "https://x.test/v1.jpg")
    source = FakeArtSource({2: [sizeless, TALL]})

    got = list_art("20260914-a3f9", 2, tools, source, order=ArtOrder.SIZE)

    assert sorted(o.label for o in got) == ["tall", "vol. 1"]
    assert got[0].label == "tall"
