from manhwatok.app.quad_art import SceneSearch, prepare_quad
from manhwatok.app.render_post import render_post
from manhwatok.domain.errors import ManhwatokError, MetadataError
from manhwatok.domain.models import ArtStyle
from manhwatok.domain.post import PostItem
from manhwatok.ports.art import ArtOption
from tests.unit.fakes import FakeArtSource, FakeCovers, FakeMetadata, make_tools, manhwa, post

PID = "20260914-a3f9"
CHAR = "https://s4.anilist.co/file/anilistcdn/character/large/"


def _pins(anilist_id, n):
    return [ArtOption(f"pin {k}", f"https://i.pinimg.com/{anilist_id}-{k}.jpg") for k in range(n)]


def _tools(tmp_path, items, metadata=None, scenes=None, messages=None):
    tools = make_tools(tmp_path, messages=messages)
    tools.metadata = metadata
    tools.scenes = scenes
    tools.posts.save(post(items=items, art=ArtStyle.QUAD))
    return tools


def _item(anilist_id, chars=(), **fields):
    """A title saved with everything AniList has (so nothing is looked up again)."""
    urls = [CHAR + c for c in chars]
    return PostItem(
        manhwa=manhwa(
            anilist_id=anilist_id,
            character_url=urls[0] if urls else "",
            character_urls=urls,
            synonyms=[],
        ),
        hook="h",
        **fields,
    )


def test_titles_saved_with_one_character_get_the_rest_from_anilist(tmp_path):
    meta = FakeMetadata()
    meta.character_urls = {1: [CHAR + "a", CHAR + "b", CHAR + "c"]}
    old = PostItem(manhwa=manhwa(anilist_id=1, character_url=CHAR + "a"), hook="h")
    tools = _tools(tmp_path, [old, _item(2, ["x", "y", "z", "w"])], metadata=meta)
    prepare_quad(PID, tools)
    assert meta.extra_lookups == [[1]]  # title 2 was saved with everything
    saved = tools.posts.get(PID).items[0].manhwa
    assert saved.character_urls == [CHAR + "a", CHAR + "b", CHAR + "c"]
    prepare_quad(PID, tools)
    assert meta.extra_lookups == [[1]]  # saved, so never asked again


def test_an_anilist_outage_keeps_the_known_character(tmp_path):
    messages = []
    meta = FakeMetadata()
    meta.extra_error = MetadataError("AniList unreachable: boom")
    old = PostItem(manhwa=manhwa(anilist_id=1, character_url=CHAR + "a"), hook="h")
    tools = _tools(tmp_path, [old], metadata=meta, messages=messages)
    prepare_quad(PID, tools)
    assert tools.posts.get(PID).items[0].manhwa.characters == [CHAR + "a"]
    assert any("AniList unreachable" in m for m in messages)


def test_scenes_fill_only_the_gaps_the_characters_leave(tmp_path):
    pins = FakeArtSource({1: _pins(1, 6), 2: _pins(2, 6)})
    tools = _tools(tmp_path, [_item(1, ["a"]), _item(2, ["a", "b", "c", "d"])], scenes=pins)
    prepare_quad(PID, tools)
    items = tools.posts.get(PID).items
    assert len(items[0].scenes) == 3
    assert items[1].scenes == []
    folder = tools.posts.folder(PID)
    assert all((folder / name).is_file() for name in items[0].scenes)
    assert all(name.startswith("scene-1-") for name in items[0].scenes)


def test_picked_art_counts_as_one_of_the_four(tmp_path):
    pins = FakeArtSource({1: _pins(1, 6)})
    tools = _tools(tmp_path, [_item(1, ["a"])], scenes=pins)
    folder = tools.posts.folder(PID)
    (folder / "art-1.jpg").write_bytes(b"x")
    items = tools.posts.get(PID).items
    tools.posts.save(
        tools.posts.get(PID).model_copy(
            update={"items": [items[0].model_copy(update={"custom_art": "art-1.jpg"})]}
        )
    )
    prepare_quad(PID, tools)
    assert len(tools.posts.get(PID).items[0].scenes) == 2


def test_scenes_are_kept_across_renders_and_replaced_on_request(tmp_path):
    pins = FakeArtSource({1: _pins(1, 12)})
    tools = _tools(tmp_path, [_item(1)], scenes=pins)
    prepare_quad(PID, tools)
    first = tools.posts.get(PID).items[0].scenes
    fetched = len(pins.fetched)
    prepare_quad(PID, tools)
    assert tools.posts.get(PID).items[0].scenes == first
    assert len(pins.fetched) == fetched  # nothing new searched or downloaded
    prepare_quad(PID, tools, SceneSearch(pins, pick=5, replace=True))
    again = tools.posts.get(PID).items[0].scenes
    assert len(again) == 4
    folder = tools.posts.folder(PID)
    assert sorted(p.name for p in folder.glob("scene-*")) == sorted(again)


def test_no_title_gets_a_scene_another_already_has(tmp_path):
    same = _pins(9, 2)
    pins = FakeArtSource({1: same + _pins(1, 4), 2: same + _pins(2, 4)})
    tools = _tools(tmp_path, [_item(1, ["a", "b"]), _item(2, ["a", "b"])], scenes=pins)
    prepare_quad(PID, tools)
    items = tools.posts.get(PID).items
    folder = tools.posts.folder(PID)
    blobs = [(folder / n).read_bytes() for it in items for n in it.scenes]
    assert len(blobs) == 4 and len(set(blobs)) == 4


def test_a_failed_search_warns_once_and_still_renders(tmp_path):
    messages = []
    pins = FakeArtSource(error=ManhwatokError("gallery-dl is not installed"))
    tools = _tools(tmp_path, [_item(1), _item(2)], scenes=pins, messages=messages)
    slides = render_post(PID, tools)
    assert len(slides) == 4
    assert sum("gallery-dl" in m for m in messages) == 1
    assert len(pins.tags) == 1  # stopped after the first title


def test_the_search_asks_for_the_given_words(tmp_path):
    pins = FakeArtSource({1: _pins(1, 4)})
    tools = _tools(tmp_path, [_item(1)], scenes=pins)
    prepare_quad(PID, tools, SceneSearch(pins, tag="fight scene"))
    assert pins.tags == ["fight scene"]


def test_other_styles_prepare_nothing(tmp_path):
    meta = FakeMetadata()
    pins = FakeArtSource({1: _pins(1, 4)})
    tools = _tools(tmp_path, [_item(1)], metadata=meta, scenes=pins)
    tools.posts.save(tools.posts.get(PID).model_copy(update={"art": ArtStyle.SCENE}))
    render_post(PID, tools)
    assert meta.extra_lookups == [] and pins.tags == []


def test_wide_pictures_are_skipped_for_a_quad_square(tmp_path):
    wide = ArtOption("wide", "https://i.pinimg.com/wide.jpg", 4096, 1297)
    tall = ArtOption("tall", "https://i.pinimg.com/tall.jpg", 1080, 1920)
    pins = FakeArtSource({1: [wide, tall]})
    tools = _tools(tmp_path, [_item(1, ["a", "b", "c"])], scenes=pins)
    prepare_quad(PID, tools)
    assert pins.fetched == ["https://i.pinimg.com/tall.jpg"]


def test_a_search_asked_for_fills_all_four_squares_with_scenes(tmp_path):
    pins = FakeArtSource({1: _pins(1, 8)})
    tools = _tools(tmp_path, [_item(1, ["a", "b", "c", "d"])], scenes=pins)
    prepare_quad(PID, tools, SceneSearch(pins, tag="fight scene", fill=True))
    assert len(tools.posts.get(PID).items[0].scenes) == 4  # characters don't take squares


def test_scenes_lead_the_grid_then_picked_art_then_characters(tmp_path):
    covers = FakeCovers(
        {1: tmp_path / "1.jpg"},
        characters={1: [tmp_path / f"c{k}.png" for k in range(4)]},
    )
    tools = make_tools(tmp_path, covers=covers)
    folder = tools.posts.folder(PID)
    folder.mkdir(parents=True)
    for name in ("art-1.jpg", "scene-1-1.jpg", "scene-1-2.jpg"):
        (folder / name).write_bytes(b"x")
    scenes = ["scene-1-1.jpg", "scene-1-2.jpg"]
    item = _item(1, ["a", "b", "c", "d"], custom_art="art-1.jpg", scenes=scenes)
    tools.posts.save(post(items=[item], art=ArtStyle.QUAD))
    render_post(PID, tools)
    _, passed = tools.renderer.calls[0]
    assert passed[1].gallery == (
        folder / "scene-1-1.jpg",
        folder / "scene-1-2.jpg",
        folder / "art-1.jpg",
        tmp_path / "c0.png",
    )
    assert covers.character_calls == [1]  # only the one character that still fits


def test_four_kept_scenes_survive_a_plain_render(tmp_path):
    pins = FakeArtSource({1: _pins(1, 8)})
    tools = _tools(tmp_path, [_item(1, ["a", "b", "c", "d"])], scenes=pins)
    prepare_quad(PID, tools, SceneSearch(pins, fill=True))
    kept = tools.posts.get(PID).items[0].scenes
    prepare_quad(PID, tools)
    assert tools.posts.get(PID).items[0].scenes == kept


def _hue(url):
    import hashlib

    return tuple(hashlib.md5(url.encode()).digest()[:3])


def test_pictures_with_speech_bubbles_are_passed_over(tmp_path):
    from PIL import Image

    pins = FakeArtSource({1: _pins(1, 6)})
    tools = _tools(tmp_path, [_item(1, ["a", "b"])], scenes=pins)
    bubbly = {_hue(o.url) for o in _pins(1, 6)[:2]}  # the first two have words on them

    def has_text(path):
        with Image.open(path) as img:
            return img.convert("RGB").getpixel((0, 0)) in bubbly

    tools.has_text = has_text
    prepare_quad(PID, tools)
    folder = tools.posts.folder(PID)
    kept = tools.posts.get(PID).items[0].scenes
    assert len(kept) == 2
    for name in kept:
        with Image.open(folder / name) as img:
            assert img.convert("RGB").getpixel((0, 0)) not in bubbly


def test_the_same_picture_at_another_size_is_not_used_twice(tmp_path):
    from PIL import Image, ImageDraw

    class Resized(FakeArtSource):
        """Every option is the same drawing, at a different size — a repin, re-encoded."""

        def fetch(self, option, into):
            into.mkdir(parents=True, exist_ok=True)
            size = 200 + 40 * len(self.fetched)
            self.fetched.append(option.url)
            img = Image.new("RGB", (size, size * 2), (240, 240, 240))
            ImageDraw.Draw(img).ellipse((size // 4, size // 2, size, size * 2), fill=(20, 20, 90))
            path = into / "picture.jpg"
            img.save(path)
            return path

    pins = Resized({1: _pins(1, 6)})
    tools = _tools(tmp_path, [_item(1, ["a", "b"])], scenes=pins)
    prepare_quad(PID, tools)
    assert len(tools.posts.get(PID).items[0].scenes) == 1


def test_quad_scenes_prefer_the_most_liked_by_default(tmp_path):
    loved = ArtOption("loved", "https://i.pinimg.com/loved.jpg", 1080, 1920, likes=2000)
    meh = ArtOption("meh", "https://i.pinimg.com/meh.jpg", 1080, 1920, likes=3)
    pins = FakeArtSource({1: [meh, loved]})
    tools = _tools(tmp_path, [_item(1, ["a", "b", "c"])], scenes=pins)
    prepare_quad(PID, tools)
    assert pins.fetched == ["https://i.pinimg.com/loved.jpg"]
