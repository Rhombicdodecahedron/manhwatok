"""Editing a post's picks keeps to its kind (final review findings 1-3)."""

from dataclasses import replace

import pytest

from manhwatok.app.edit_post import edit_post, update_picks
from manhwatok.domain.errors import DraftError
from manhwatok.domain.models import CharacterPick, PostKind
from manhwatok.domain.post import MAX_GUESS, PostItem
from tests.unit.fakes import FakeMetadata, ScriptedEditor, make_tools, manhwa, post

PID = "20260914-a3f9"


def _titles(n):
    return [manhwa(anilist_id=i, title=f"T{i}") for i in range(1, n + 1)]


def _saved(tmp_path, kind, items, candidates, **tools_fields):
    tools = replace(make_tools(tmp_path), **tools_fields)
    tools.posts.save(post(items=items, candidates=candidates, kind=kind))
    return tools


def test_editing_a_versus_post_down_to_an_odd_count_is_refused(tmp_path):
    titles = _titles(4)
    tools = _saved(tmp_path, PostKind.VERSUS, [PostItem(manhwa=m) for m in titles], titles)
    with pytest.raises(DraftError, match="pairs"):
        update_picks(PID, "T", [PostItem(manhwa=m) for m in titles[:3]], tools)


def test_editing_a_guess_post_past_its_cap_is_refused(tmp_path):
    titles = _titles(MAX_GUESS + 1)
    tools = _saved(tmp_path, PostKind.GUESS, [PostItem(manhwa=titles[0])], titles)
    with pytest.raises(DraftError, match=str(MAX_GUESS)):
        update_picks(PID, "T", [PostItem(manhwa=m) for m in titles], tools)


def _characters_post(tmp_path, meta=None):
    titles = _titles(3)
    ranked = [
        PostItem(manhwa=titles[0], character=CharacterPick(name="Jin", index=1, image_url="u1")),
        PostItem(manhwa=titles[1], character=CharacterPick(name="Hae", index=0, image_url="u2")),
    ]
    return _saved(tmp_path, PostKind.CHARACTERS, ranked, titles, metadata=meta), titles


def test_editing_a_characters_post_keeps_each_picks_character(tmp_path):
    tools, titles = _characters_post(tmp_path)
    update_picks(PID, "New title", [PostItem(manhwa=titles[1]), PostItem(manhwa=titles[0])], tools)
    saved = tools.posts.get(PID)
    assert [i.character.name for i in saved.items] == ["Hae", "Jin"]


def test_a_title_added_to_a_characters_post_gets_its_character(tmp_path):
    meta = FakeMetadata()
    meta.cast[3] = [CharacterPick(name="Ria", index=0, image_url="u3")]
    tools, titles = _characters_post(tmp_path, meta)
    update_picks(PID, "T", [PostItem(manhwa=m) for m in titles], tools)
    assert [i.character.name for i in tools.posts.get(PID).items] == ["Jin", "Hae", "Ria"]


def test_a_title_without_characters_added_to_a_characters_post_is_refused_by_name(tmp_path):
    tools, titles = _characters_post(tmp_path, FakeMetadata())
    with pytest.raises(Exception, match="T3"):
        update_picks(PID, "T", [PostItem(manhwa=m) for m in titles], tools)


def test_editing_a_characters_post_in_the_editor_keeps_the_characters(tmp_path):
    tools, _ = _characters_post(tmp_path)
    tools = replace(tools, editor=ScriptedEditor(lambda text: text.replace("title: ", "title: New ")))
    edit_post(PID, tools)
    assert [i.character.name for i in tools.posts.get(PID).items] == ["Jin", "Hae"]


def test_the_editor_can_switch_a_picks_character(tmp_path):
    meta = FakeMetadata()
    meta.cast[1] = [CharacterPick(name="A", index=0, image_url="a"), CharacterPick(name="B", index=1, image_url="b")]
    tools, _ = _characters_post(tmp_path, meta)

    def respond(text):
        lines = text.splitlines()
        return "\n".join(line + " | 1" if line.startswith("1 |") else line for line in lines) + "\n"

    tools = replace(tools, editor=ScriptedEditor(respond))
    edit_post(PID, tools)
    assert tools.posts.get(PID).items[0].character.name == "A"
