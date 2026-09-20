from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from manhwatok.adapters.pillow_renderer import PillowRenderer
from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.delete_post import delete_post
from manhwatok.app.export_post import export_post
from manhwatok.app.render_post import CAPTION_FILE, choose_cover, render_post
from manhwatok.domain.errors import (
    DraftError,
    ManhwatokError,
    NotRendered,
    PostNotFound,
    StorageError,
)
from manhwatok.domain.post import PostItem
from manhwatok.domain.models import ArtStyle, CoverStyle
from manhwatok.ports.posts import SlideArt
from tests.unit.fakes import (
    FakeCovers,
    FakeHistory,
    cover_file,
    make_tools,
    manhwa,
    post,
)

NOW = datetime(2026, 9, 15, 9, 30, tzinfo=timezone.utc)


def _export(tools, dest, history=None, now=NOW):
    history = history if history is not None else FakeHistory()
    return export_post("20260914-a3f9", tools.posts, history, dest, now=now)


# --- render ------------------------------------------------------------------------------


def test_render_writes_slides_and_caption(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    slides = render_post("20260914-a3f9", tools)
    folder = tools.posts.folder("20260914-a3f9")
    assert [s.name for s in slides] == ["01.png", "02.png", "03.png", "04.png", "05.png"]
    assert (
        (folder / "caption.txt")
        .read_text()
        .startswith("Manhwa where the MC regresses\n\n1. Title 1")
    )
    _, covers = tools.renderer.calls[0]
    assert covers == {
        1: SlideArt(tmp_path / "1.jpg", None),
        2: SlideArt(tmp_path / "2.jpg", None),
        3: SlideArt(tmp_path / "3.jpg", None),
    }


def test_render_stops_downloading_after_first_cover_failure(tmp_path):
    messages = []
    covers = FakeCovers({1: tmp_path / "1.jpg", 3: tmp_path / "3.jpg"}, fail={2})
    tools = make_tools(tmp_path, covers=covers, messages=messages)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed == {
        1: SlideArt(tmp_path / "1.jpg", None),
        2: SlideArt(None, None),
        3: SlideArt(None, None),
    }
    assert covers.calls == [1, 2]
    assert len(messages) == 1
    assert "plain backgrounds" in messages[0]


def test_render_uses_cache_for_items_after_a_failure(tmp_path):
    messages = []
    covers = FakeCovers({1: tmp_path / "1.jpg", 3: tmp_path / "3.jpg"}, fail={2}, on_disk={3})
    tools = make_tools(tmp_path, covers=covers, messages=messages)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed == {
        1: SlideArt(tmp_path / "1.jpg", None),
        2: SlideArt(None, None),
        3: SlideArt(tmp_path / "3.jpg", None),
    }
    assert covers.calls == [1, 2]
    assert len(messages) == 1


def test_render_skips_items_without_a_cover_url_without_failing(tmp_path):
    messages = []
    items = [
        PostItem(manhwa=manhwa(anilist_id=1, cover_url=""), hook="Hook 1"),
        PostItem(manhwa=manhwa(anilist_id=2), hook="Hook 2"),
    ]
    tools = make_tools(tmp_path, messages=messages)
    tools.posts.save(post(items=items))
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed == {1: SlideArt(None, None), 2: SlideArt(tmp_path / "2.jpg", None)}
    assert messages == []
    assert tools.covers.calls == [2]


def test_render_unfinished_post(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(items=[]))
    with pytest.raises(DraftError, match="fix with: manhwatok edit 20260914-a3f9"):
        render_post("20260914-a3f9", tools)


def test_render_unknown_post(tmp_path):
    with pytest.raises(PostNotFound):
        render_post("20260914-ffff", make_tools(tmp_path))


def test_render_caption_write_failure_raises_storage_error(tmp_path, monkeypatch):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    real_write_text = Path.write_text

    def boom(self, *args, **kwargs):
        if self.name == CAPTION_FILE:
            raise OSError("disk full")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", boom)
    with pytest.raises(StorageError):
        render_post("20260914-a3f9", tools)


def test_render_with_real_renderer(tmp_path):
    covers = FakeCovers({i: cover_file(tmp_path / "covers", i) for i in (1, 2, 3)})
    tools = make_tools(tmp_path, covers=covers, renderer=PillowRenderer())
    tools.posts.save(post())
    assert len(render_post("20260914-a3f9", tools)) == 5


# --- export ------------------------------------------------------------------------------


def test_export_copies_slides_and_caption(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    dest = _export(tools, tmp_path / "exports")
    assert dest == tmp_path / "exports" / "20260914-a3f9"
    assert sorted(f.name for f in dest.iterdir()) == [
        "01.png",
        "02.png",
        "03.png",
        "04.png",
        "05.png",
        "caption.txt",
    ]


def test_export_replaces_stale_slides_in_destination(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    stale = tmp_path / "exports" / "20260914-a3f9"
    stale.mkdir(parents=True)
    (stale / "09.png").write_bytes(b"old")
    _export(tools, tmp_path / "exports")
    assert not (stale / "09.png").exists()


def test_export_before_render(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    with pytest.raises(NotRendered, match="run: manhwatok render 20260914-a3f9"):
        _export(tools, tmp_path / "exports")


def test_export_unfinished_post(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(items=[]))
    with pytest.raises(DraftError):
        _export(tools, tmp_path / "exports")


def test_export_destination_blocked_by_a_file_raises_storage_error(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    blocker = tmp_path / "exports"
    blocker.write_bytes(b"not a directory")
    with pytest.raises(StorageError):
        _export(tools, blocker)


def test_first_export_of_an_account_post_records_history(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(account="reads"))
    render_post("20260914-a3f9", tools)
    history = FakeHistory()
    _export(tools, tmp_path / "exports", history)
    assert history.records == [("reads", "20260914-a3f9", [1, 2, 3], NOW)]
    assert tools.posts.get("20260914-a3f9").exported_at == NOW


def _history_rows(store) -> list[tuple]:
    return store.query(
        StorageError,
        "SELECT account, anilist_id, post_id, exported_at FROM history ORDER BY anilist_id",
    )


def test_re_export_keeps_the_first_date_and_adds_no_rows(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(account="reads"))
    render_post("20260914-a3f9", tools)
    with SqliteStore(tmp_path / "m.db") as store:
        _export(tools, tmp_path / "exports", store.history)
        first = _history_rows(store)
        _export(tools, tmp_path / "again", store.history, now=NOW + timedelta(days=3))
        assert _history_rows(store) == first
    assert [row[1] for row in first] == [1, 2, 3]
    assert tools.posts.get("20260914-a3f9").exported_at == NOW


def test_re_export_after_an_edit_records_the_new_title_with_the_first_date(tmp_path):
    """Export, swap title 3 for title 9, export again: 9 is protected from repeats too, dated
    like the rest of the post (its first export), and 3 stays recorded — it was posted."""
    tools = make_tools(tmp_path)
    tools.posts.save(post(account="reads"))
    render_post("20260914-a3f9", tools)
    with SqliteStore(tmp_path / "m.db") as store:
        _export(tools, tmp_path / "exports", store.history)
        exported = tools.posts.get("20260914-a3f9")
        swapped = exported.items[:2] + [PostItem(manhwa=manhwa(anilist_id=9), hook="Hook 9")]
        tools.posts.save(exported.model_copy(update={"items": swapped}))
        render_post("20260914-a3f9", tools)
        _export(tools, tmp_path / "again", store.history, now=NOW + timedelta(days=3))

        assert store.history.recent("reads", NOW) == {1, 2, 3, 9}
        assert store.history.recent("reads", NOW + timedelta(microseconds=1)) == set()
        assert len(_history_rows(store)) == 4
    assert tools.posts.get("20260914-a3f9").exported_at == NOW


def test_export_without_account_records_nothing(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    history = FakeHistory()
    _export(tools, tmp_path / "exports", history)
    _export(tools, tmp_path / "again", history)
    assert history.records == []
    assert tools.posts.get("20260914-a3f9").exported_at is None


# --- delete ------------------------------------------------------------------------------


def test_delete_removes_the_post_folder_and_keeps_history(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(account="reads"))
    render_post("20260914-a3f9", tools)
    with SqliteStore(tmp_path / "m.db") as store:
        _export(tools, tmp_path / "exports", store.history)
        delete_post("20260914-a3f9", tools.posts)
        assert not tools.posts.folder("20260914-a3f9").exists()
        assert store.history.recent("reads", NOW) == {1, 2, 3}
    assert (tmp_path / "exports" / "20260914-a3f9" / "caption.txt").is_file()


def test_delete_unknown_post(tmp_path):
    with pytest.raises(PostNotFound, match="no post 20260914-ffff"):
        delete_post("20260914-ffff", make_tools(tmp_path).posts)


def test_delete_failure_raises_storage_error(tmp_path, monkeypatch):
    tools = make_tools(tmp_path)
    tools.posts.save(post())

    def boom(path):
        raise OSError("busy")

    monkeypatch.setattr("manhwatok.app.delete_post.shutil.rmtree", boom)
    with pytest.raises(StorageError, match="could not delete post 20260914-a3f9"):
        delete_post("20260914-a3f9", tools.posts)


# --- background art (Phase 5) ---------------------------------------------------------------


def _art_post(**overrides):
    items = [
        PostItem(manhwa=manhwa(anilist_id=1, banner_url="https://x.test/1-banner.jpg"), hook="a"),
        PostItem(manhwa=manhwa(anilist_id=2, banner_url=""), hook="b"),
    ]
    return post(items=items, **overrides)


def test_render_fetches_banners_for_background_art(tmp_path):
    covers = FakeCovers(
        {1: tmp_path / "1.jpg", 2: tmp_path / "2.jpg"}, banners={1: tmp_path / "1-banner.jpg"}
    )
    tools = make_tools(tmp_path, covers=covers)
    tools.posts.save(_art_post(art=ArtStyle.BACKGROUND))
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed == {
        1: SlideArt(tmp_path / "1.jpg", tmp_path / "1-banner.jpg"),
        2: SlideArt(tmp_path / "2.jpg", None),  # no banner_url — falls back to the cover
    }
    assert covers.banner_calls == [1]  # never asked for the one with no banner_url


def test_render_downloads_no_banners_when_art_is_none(tmp_path):
    covers = FakeCovers(
        {1: tmp_path / "1.jpg", 2: tmp_path / "2.jpg"}, banners={1: tmp_path / "1-banner.jpg"}
    )
    tools = make_tools(tmp_path, covers=covers)
    tools.posts.save(_art_post())
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed[1].banner is None
    assert covers.banner_calls == []


def test_render_downloads_no_banners_or_characters_for_scene_art(tmp_path):
    """A scene draws the pin, or the cover cropped to fill — never a banner or a portrait."""
    covers = FakeCovers(
        {1: tmp_path / "1.jpg", 2: tmp_path / "2.jpg"},
        banners={1: tmp_path / "1-banner.jpg"},
        characters={1: tmp_path / "1-char.jpg"},
    )
    tools = make_tools(tmp_path, covers=covers)
    tools.posts.save(_art_post(art=ArtStyle.SCENE))
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed[1] == SlideArt(tmp_path / "1.jpg", None)
    assert covers.banner_calls == []
    assert covers.character_calls == []


def test_render_survives_a_banner_download_failure(tmp_path):
    messages = []
    covers = FakeCovers({1: tmp_path / "1.jpg", 2: tmp_path / "2.jpg"}, fail_banners={1})
    tools = make_tools(tmp_path, covers=covers, messages=messages)
    tools.posts.save(_art_post(art=ArtStyle.BACKGROUND))
    slides = render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed[1] == SlideArt(tmp_path / "1.jpg", None)  # the cover still renders
    assert len(slides) == 4
    assert len(messages) == 1 and "banner" in messages[0]


def _char_post(**overrides):
    items = [
        PostItem(manhwa=manhwa(anilist_id=1, character_url="https://x.test/1-char.png"), hook="a"),
        PostItem(manhwa=manhwa(anilist_id=2, character_url=""), hook="b"),
    ]
    return post(items=items, **overrides)


def test_render_fetches_character_images_for_character_art(tmp_path):
    covers = FakeCovers(
        {1: tmp_path / "1.jpg", 2: tmp_path / "2.jpg"}, characters={1: tmp_path / "1-char.png"}
    )
    tools = make_tools(tmp_path, covers=covers)
    tools.posts.save(_char_post(art=ArtStyle.CHARACTER))
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed[1].character == tmp_path / "1-char.png"
    assert passed[2].character is None  # no character_url — the cover stands in
    assert covers.character_calls == [1]
    assert covers.banner_calls == []  # this style needs no banner


@pytest.mark.parametrize("art", [ArtStyle.NONE, ArtStyle.BACKGROUND, ArtStyle.SCENE])
def test_render_fetches_characters_for_the_quad_cover_in_every_style(tmp_path, art):
    covers = FakeCovers(
        {1: tmp_path / "1.jpg", 2: tmp_path / "2.jpg"}, characters={1: tmp_path / "1-char.png"}
    )
    tools = make_tools(tmp_path, covers=covers)
    tools.posts.save(_char_post(art=art))
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed[1].character == tmp_path / "1-char.png"
    assert covers.character_calls == [1]


def test_render_fetches_characters_for_the_first_four_titles_only(tmp_path):
    items = [
        PostItem(manhwa=manhwa(anilist_id=i, character_url=f"https://x.test/{i}.png"), hook="h")
        for i in range(1, 7)
    ]
    covers = FakeCovers(
        {i: tmp_path / f"{i}.jpg" for i in range(1, 7)},
        characters={i: tmp_path / f"{i}-char.png" for i in range(1, 7)},
    )
    tools = make_tools(tmp_path, covers=covers)
    tools.posts.save(post(items=items))
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert covers.character_calls == [1, 2, 3, 4]
    assert passed[5].character is None


def test_render_survives_a_character_download_failure(tmp_path):
    messages = []
    covers = FakeCovers({1: tmp_path / "1.jpg", 2: tmp_path / "2.jpg"}, fail_characters={1})
    tools = make_tools(tmp_path, covers=covers, messages=messages)
    tools.posts.save(_char_post(art=ArtStyle.CHARACTER))
    slides = render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed[1] == SlideArt(tmp_path / "1.jpg", None, None)
    assert len(slides) == 4
    assert len(messages) == 1 and "character" in messages[0]


# --- hand-picked art -------------------------------------------------------------------------


def _picked_post(name="art-1.png", **overrides):
    items = [
        PostItem(manhwa=manhwa(anilist_id=1), hook="a", custom_art=name),
        PostItem(manhwa=manhwa(anilist_id=2), hook="b"),
    ]
    return post(items=items, **overrides)


def test_render_passes_hand_picked_art_from_the_post_folder(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(_picked_post())
    picked = tools.posts.folder("20260914-a3f9") / "art-1.png"
    picked.write_bytes(b"picked")
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed[1].custom == picked
    assert passed[2].custom is None


def test_render_ignores_hand_picked_art_whose_file_has_gone(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(_picked_post())
    slides = render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed[1].custom is None
    assert len(slides) == 4  # still renders, on the cover


def test_render_still_fetches_covers_for_a_title_with_picked_art(tmp_path):
    """The cover is the slide's backdrop, so it is still wanted."""
    tools = make_tools(tmp_path)
    tools.posts.save(_picked_post())
    (tools.posts.folder("20260914-a3f9") / "art-1.png").write_bytes(b"picked")
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed[1].cover == tmp_path / "1.jpg"


# --- choosing a cover version --------------------------------------------------------------------


def _rendered_versions(tools):
    folder = tools.posts.folder("20260914-a3f9")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "01.png").write_bytes(b"fan")
    for style in CoverStyle:
        (folder / f"cover-{style.value}.png").write_bytes(style.value.encode())
    return folder


def test_choose_cover_saves_the_choice_and_swaps_the_first_slide(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    folder = _rendered_versions(tools)
    path = choose_cover("20260914-a3f9", CoverStyle.QUAD, tools)
    assert path == folder / "01.png"
    assert path.read_bytes() == b"quad"
    assert tools.posts.get("20260914-a3f9").cover is CoverStyle.QUAD


def test_choose_cover_before_render_saves_the_choice_and_asks_for_a_render(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    with pytest.raises(NotRendered, match="run: manhwatok render 20260914-a3f9"):
        choose_cover("20260914-a3f9", CoverStyle.HERO, tools)
    assert tools.posts.get("20260914-a3f9").cover is CoverStyle.HERO


def test_old_posts_load_with_the_fan_cover(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    path = tools.posts.folder("20260914-a3f9") / "post.json"
    import json

    data = json.loads(path.read_text())
    data.pop("cover", None)
    path.write_text(json.dumps(data))
    assert tools.posts.get("20260914-a3f9").cover is CoverStyle.FAN


# --- chapter posts ------------------------------------------------------------------------------


def _chapter_tools(tmp_path):
    from tests.unit.fakes import make_chapter_tools

    return make_chapter_tools(tmp_path)


def _saved_chapter_post(tmp_path, tools, **fields):
    from PIL import Image

    from tests.unit.fakes import chapter_part, chapter_post

    folder = tools.posts.folder("20260914-a3f9")
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for n in (1, 2):
        name = f"panel-{n:03d}.png"
        Image.new("RGB", (1080, 1920), (30 * n, 60, 90)).save(folder / name)
        names.append(name)
    post = chapter_post(chapter=chapter_part(panels=names, to_panel=2), **fields)
    tools.posts.save(post)
    return post


def test_rendering_a_chapter_post_writes_one_slide_per_panel_and_a_caption(tmp_path):
    tools = make_tools(tmp_path, renderer=PillowRenderer())
    post = _saved_chapter_post(tmp_path, tools)
    slides = render_post("20260914-a3f9", tools)
    assert [p.name for p in slides] == ["01.png", "02.png", "03.png", "04.png"]
    caption = (tools.posts.folder(post.id) / CAPTION_FILE).read_text(encoding="utf-8")
    assert "chapter 12" in caption


def test_exporting_a_chapter_post_marks_its_part_published(tmp_path):
    from manhwatok.domain.chapter import PartRecord

    tools = make_tools(tmp_path, renderer=PillowRenderer())
    _saved_chapter_post(tmp_path, tools, account="reads")
    render_post("20260914-a3f9", tools)
    ct = _chapter_tools(tmp_path)
    ct.chapters.record_part(
        PartRecord(
            anilist_id=1,
            number="12",
            language="en",
            part=1,
            parts=2,
            post_id="20260914-a3f9",
            built_at=NOW,
        )
    )
    export_post(
        "20260914-a3f9", tools.posts, FakeHistory(), tmp_path / "out", now=NOW,
        chapters=ct.chapters,
    )
    assert ct.chapters.parts(1)[0].published_at == NOW


def test_exporting_a_chapter_post_records_no_recommendation_history(tmp_path):
    tools = make_tools(tmp_path, renderer=PillowRenderer())
    _saved_chapter_post(tmp_path, tools, account="reads")
    render_post("20260914-a3f9", tools)
    history = FakeHistory()
    export_post("20260914-a3f9", tools.posts, history, tmp_path / "out", now=NOW)
    assert history.records == [] or history.records[0][2] == []


def test_deleting_a_chapter_post_frees_its_part_to_be_built_again(tmp_path):
    from manhwatok.domain.chapter import PartRecord

    tools = make_tools(tmp_path)
    _saved_chapter_post(tmp_path, tools)
    ct = _chapter_tools(tmp_path)
    ct.chapters.record_part(
        PartRecord(
            anilist_id=1, number="12", language="en", part=1, parts=2,
            post_id="20260914-a3f9", built_at=NOW,
        )
    )
    delete_post("20260914-a3f9", tools.posts, chapters=ct.chapters)
    assert ct.chapters.parts(1) == []


def test_choosing_another_cover_for_a_chapter_post_is_refused(tmp_path):
    from manhwatok.domain.models import CoverStyle

    tools = make_tools(tmp_path, renderer=PillowRenderer())
    _saved_chapter_post(tmp_path, tools)
    with pytest.raises(ManhwatokError, match="chapter post"):
        choose_cover("20260914-a3f9", CoverStyle.QUAD, tools)
