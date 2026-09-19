import pytest

from manhwatok.app.art_options import fill_art, list_art, use_art
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


# --- filling every title at once -------------------------------------------------------------


PIN1 = ArtOption("pin 1", "https://i.test/1.jpg")
PIN2 = ArtOption("pin 2", "https://i.test/2.jpg")
PIN3 = ArtOption("pin 3", "https://i.test/3.jpg")


def _own(anilist_id, n=2, **size):
    """Pictures only this title turns up, so a test about one thing is not also about repeats."""
    return [
        ArtOption(f"{anilist_id} pin {k}", f"https://i.test/{anilist_id}-{k}.jpg", **size)
        for k in range(1, n + 1)
    ]


def _art_of(tools):
    return {i.manhwa.anilist_id: i.custom_art for i in tools.posts.get("20260914-a3f9").items}


def test_filling_gives_every_title_the_sources_first_picture(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    source = FakeArtSource({1: [PIN1, PIN2], 2: [PIN2], 3: [PIN3]})

    filled = fill_art("20260914-a3f9", tools, source)

    assert filled == 3
    assert source.fetched == [PIN1.url, PIN2.url, PIN3.url]
    assert _art_of(tools) == {1: "art-1.jpg", 2: "art-2.jpg", 3: "art-3.jpg"}


def test_filling_with_pick_takes_that_picture_for_every_title(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    source = FakeArtSource({i: _own(i) for i in (1, 2, 3)})

    fill_art("20260914-a3f9", tools, source, pick=2)

    assert source.fetched == [_own(i)[1].url for i in (1, 2, 3)]


def test_filling_asks_with_the_tag_and_picks_after_ordering(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    wide = {i: _own(i, 1, width=1600, height=900)[0] for i in (1, 2, 3)}
    tall = {i: ArtOption("tall", f"https://i.test/{i}-tall.jpg", 1080, 1920) for i in (1, 2, 3)}
    source = FakeArtSource({i: [wide[i], tall[i]] for i in (1, 2, 3)})

    fill_art("20260914-a3f9", tools, source, tag="fight scene", order=ArtOrder.PORTRAIT)

    assert source.tags == ["fight scene"] * 3
    assert source.fetched == [tall[i].url for i in (1, 2, 3)]


def test_filling_leaves_titles_you_already_picked_art_for(tmp_path):
    """Picks made one by one survive a later fill, so fixing a few titles by hand is safe."""
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    use_art("20260914-a3f9", 2, VOL1, tools, FakeArtSource())
    source = FakeArtSource({i: _own(i) for i in (1, 2, 3)})

    filled = fill_art("20260914-a3f9", tools, source)

    assert filled == 2
    assert len(source.tags) == 2  # title 2 was never even searched
    assert source.fetched == [_own(1)[0].url, _own(3)[0].url]


def test_filling_with_replace_picks_again_for_every_title(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    use_art("20260914-a3f9", 2, VOL1, tools, FakeArtSource())
    source = FakeArtSource({i: _own(i) for i in (1, 2, 3)})

    filled = fill_art("20260914-a3f9", tools, source, replace=True)

    assert filled == 3
    assert _own(2)[0].url in source.fetched


def test_filling_skips_a_title_the_source_has_nothing_for_and_says_so(tmp_path):
    messages = []
    tools = make_tools(tmp_path, messages=messages)
    _saved(tmp_path, tools)
    source = FakeArtSource({1: _own(1), 3: _own(3)})

    filled = fill_art("20260914-a3f9", tools, source)

    assert filled == 2
    assert _art_of(tools)[2] == ""
    assert any("Title 2" in m and "nothing" in m for m in messages)


def test_filling_skips_a_title_with_fewer_pictures_than_the_pick(tmp_path):
    messages = []
    tools = make_tools(tmp_path, messages=messages)
    _saved(tmp_path, tools)
    source = FakeArtSource({1: _own(1), 2: _own(2, 1), 3: _own(3)})

    filled = fill_art("20260914-a3f9", tools, source, pick=2)

    assert filled == 2
    assert _art_of(tools)[2] == ""
    assert any("Title 2" in m and "only 1" in m for m in messages)


def test_filling_carries_on_past_a_picture_that_will_not_download(tmp_path):
    messages = []
    tools = make_tools(tmp_path, messages=messages)
    _saved(tmp_path, tools)
    bad = ArtOption("bad", "https://i.test/bad.jpg")
    source = FakeArtSource({1: _own(1), 2: [bad], 3: _own(3)}, broken={bad.url})

    filled = fill_art("20260914-a3f9", tools, source)

    assert filled == 2
    assert _art_of(tools)[2] == ""
    assert any("Title 2" in m and "bad.jpg" in m for m in messages)


def test_filling_tries_the_next_picture_when_one_will_not_download(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    bad = ArtOption("bad", "https://i.test/bad.jpg")
    source = FakeArtSource({1: _own(1), 2: [bad, PIN2], 3: _own(3)}, broken={bad.url})

    assert fill_art("20260914-a3f9", tools, source) == 3
    assert source.fetched[1:3] == [bad.url, PIN2.url]


def test_filling_stops_when_the_search_itself_fails(tmp_path):
    """No gallery-dl, or Pinterest down, fails every title the same way — say it once."""
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    source = FakeArtSource(error=ManhwatokError("gallery-dl is not installed"))

    with pytest.raises(ManhwatokError, match="gallery-dl"):
        fill_art("20260914-a3f9", tools, source)
    assert len(source.tags) == 1


def test_filling_reports_each_title_it_uses_a_picture_for(tmp_path):
    messages = []
    tools = make_tools(tmp_path, messages=messages)
    _saved(tmp_path, tools)

    fill_art("20260914-a3f9", tools, FakeArtSource({i: _own(i) for i in (1, 2, 3)}))

    assert any("Title 1" in m and "1 pin 1" in m for m in messages)


# --- one picture per post ----------------------------------------------------------------------


def test_filling_never_gives_two_titles_the_same_picture(tmp_path):
    """A generic search word can outweigh the title, and then every title's first result is the
    same pin. Each title takes the first one no other title in the post already has."""
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    source = FakeArtSource({1: [PIN1, PIN2], 2: [PIN1, PIN2], 3: [PIN1, PIN2, PIN3]})

    assert fill_art("20260914-a3f9", tools, source) == 3
    assert source.fetched == [PIN1.url, PIN2.url, PIN3.url]  # a known repeat isn't downloaded


def test_filling_spots_the_same_picture_under_another_address(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    repin = ArtOption("repin", "https://i.test/repin.jpg")
    source = FakeArtSource(
        {1: [PIN1], 2: [repin, PIN2], 3: _own(3)}, twins={repin.url: PIN1.url}
    )

    fill_art("20260914-a3f9", tools, source)

    assert source.fetched[:3] == [PIN1.url, repin.url, PIN2.url]
    folder = tools.posts.folder("20260914-a3f9")
    assert (folder / "art-1.jpg").read_bytes() != (folder / "art-2.jpg").read_bytes()


def test_filling_does_not_reuse_a_picture_a_kept_title_already_has(tmp_path):
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    use_art("20260914-a3f9", 2, PIN1, tools, FakeArtSource())
    source = FakeArtSource({1: [PIN1, PIN2], 3: _own(3)})

    fill_art("20260914-a3f9", tools, source)

    assert _art_of(tools)[1] == "art-1.jpg"
    folder = tools.posts.folder("20260914-a3f9")
    assert (folder / "art-1.jpg").read_bytes() != (folder / "art-2.jpg").read_bytes()


def test_filling_skips_a_title_whose_every_picture_is_already_used(tmp_path):
    messages = []
    tools = make_tools(tmp_path, messages=messages)
    _saved(tmp_path, tools)
    source = FakeArtSource({1: [PIN1], 2: [PIN1], 3: _own(3)})

    assert fill_art("20260914-a3f9", tools, source) == 2
    assert _art_of(tools)[2] == ""
    assert any("Title 2" in m and "already" in m for m in messages)


def test_replacing_does_not_count_a_titles_own_old_picture_as_taken(tmp_path):
    """Re-picking with the same search should land on the same picture, not be pushed off it by
    the file it is about to replace."""
    tools = make_tools(tmp_path)
    _saved(tmp_path, tools)
    source = FakeArtSource({i: _own(i) for i in (1, 2, 3)})
    fill_art("20260914-a3f9", tools, source)

    fill_art("20260914-a3f9", tools, source, replace=True)

    assert source.fetched[3:] == [_own(i)[0].url for i in (1, 2, 3)]


def test_popular_puts_the_most_liked_first():
    from manhwatok.app.art_options import arrange
    from manhwatok.domain.models import ArtOrder

    a = ArtOption("a", "https://x.test/a.jpg", likes=10)
    b = ArtOption("b", "https://x.test/b.jpg", likes=900)
    c = ArtOption("c", "https://x.test/c.jpg")
    assert arrange([a, b, c], ArtOrder.POPULAR) == [b, a, c]


def test_fill_passes_over_pictures_with_words_on_them(tmp_path):
    from manhwatok.app.art_options import fill_art
    from tests.unit.fakes import FakeArtSource, make_tools, post

    tools = make_tools(tmp_path)
    tools.posts.save(post())
    source = FakeArtSource({1: [VOL1, VOL2]})
    checked = []

    def has_text(path):
        checked.append(path)
        return len(checked) == 1  # the first picture has a speech bubble

    tools.has_text = has_text
    fill_art("20260914-a3f9", tools, source)
    assert source.fetched[:2] == [VOL1.url, VOL2.url]
    assert tools.posts.get("20260914-a3f9").items[0].custom_art
