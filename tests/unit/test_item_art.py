import pytest

from manhwatok.app.item_art import clear_item_art, set_item_art
from manhwatok.domain.errors import ManhwatokError, PostNotFound
from manhwatok.domain.post import PostItem
from tests.unit.fakes import make_tools, manhwa, post


def _picture(tmp_path, name="pick.png", data=b"\x89PNG not really"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _saved(tmp_path, ids=(11, 22)):
    tools = make_tools(tmp_path)
    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"Title {i}"), hook="h") for i in ids]
    tools.posts.save(post(items=items))
    return tools


def test_set_copies_the_picture_into_the_post_folder(tmp_path):
    tools = _saved(tmp_path)
    kept = set_item_art("20260914-a3f9", 11, _picture(tmp_path), tools)
    folder = tools.posts.folder("20260914-a3f9")
    assert kept == folder / "art-11.png"
    assert kept.read_bytes() == b"\x89PNG not really"
    item = tools.posts.get("20260914-a3f9").items[0]
    assert item.custom_art == "art-11.png"


def test_set_leaves_the_other_titles_alone(tmp_path):
    tools = _saved(tmp_path)
    set_item_art("20260914-a3f9", 11, _picture(tmp_path), tools)
    assert tools.posts.get("20260914-a3f9").items[1].custom_art == ""


def test_set_replaces_an_earlier_pick_without_leaving_the_old_file(tmp_path):
    tools = _saved(tmp_path)
    set_item_art("20260914-a3f9", 11, _picture(tmp_path, "one.png"), tools)
    set_item_art("20260914-a3f9", 11, _picture(tmp_path, "two.jpg", b"jpegish"), tools)
    folder = tools.posts.folder("20260914-a3f9")
    assert tools.posts.get("20260914-a3f9").items[0].custom_art == "art-11.jpg"
    assert (folder / "art-11.jpg").read_bytes() == b"jpegish"
    assert not (folder / "art-11.png").exists()


def test_set_names_the_titles_when_the_id_is_not_in_the_post(tmp_path):
    tools = _saved(tmp_path)
    with pytest.raises(ManhwatokError, match="11"):
        set_item_art("20260914-a3f9", 999, _picture(tmp_path), tools)


def test_set_rejects_a_missing_file(tmp_path):
    tools = _saved(tmp_path)
    with pytest.raises(ManhwatokError, match="no such file"):
        set_item_art("20260914-a3f9", 11, tmp_path / "nope.png", tools)


def test_set_rejects_an_empty_file(tmp_path):
    tools = _saved(tmp_path)
    with pytest.raises(ManhwatokError, match="is empty"):
        set_item_art("20260914-a3f9", 11, _picture(tmp_path, "empty.png", b""), tools)


def test_set_rejects_a_file_that_is_not_a_picture(tmp_path):
    tools = _saved(tmp_path)
    with pytest.raises(ManhwatokError, match="not a picture"):
        set_item_art("20260914-a3f9", 11, _picture(tmp_path, "notes.txt", b"hello"), tools)


def test_set_on_an_unknown_post(tmp_path):
    tools = _saved(tmp_path)
    with pytest.raises(PostNotFound):
        set_item_art("20260914-0000", 11, _picture(tmp_path), tools)


def test_clear_removes_the_picture_and_the_record(tmp_path):
    tools = _saved(tmp_path)
    kept = set_item_art("20260914-a3f9", 11, _picture(tmp_path), tools)
    clear_item_art("20260914-a3f9", 11, tools)
    assert not kept.exists()
    assert tools.posts.get("20260914-a3f9").items[0].custom_art == ""


def test_clear_is_quiet_when_there_was_nothing_to_clear(tmp_path):
    tools = _saved(tmp_path)
    clear_item_art("20260914-a3f9", 11, tools)
    assert tools.posts.get("20260914-a3f9").items[0].custom_art == ""
