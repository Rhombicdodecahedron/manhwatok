from datetime import datetime, timezone

import pytest

from manhwatok.app.build_post import build_post
from manhwatok.app.edit_post import edit_post
from manhwatok.domain.errors import DraftError, ManhwatokError
from manhwatok.domain.models import SearchQuery
from tests.unit.fakes import FakeCovers, FakeMetadata, ScriptedEditor, make_tools, manhwa, post

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
Q = SearchQuery(tags=["Revenge"])
CANDIDATES = [
    manhwa(anilist_id=11, title="Doom Breaker", description="Sent back ten years. More."),
    manhwa(anilist_id=22, title="Kubera", description="Gods and more gods. More."),
]


# --- build -------------------------------------------------------------------------------


def _build(tools, title="MC *regresses*", accent="#43C9E4", results=CANDIDATES):
    return build_post(Q, title, "#manhwa", accent, FakeMetadata(results), None, tools, now=NOW)


def test_build_prefills_draft_saves_and_renders(tmp_path):
    editor = ScriptedEditor(lambda text: text.replace("Sent back ten years.", "Ten years back!"))
    tools = make_tools(tmp_path, editor=editor)
    built, slides = _build(tools)
    shown = editor.shown[0]
    assert "title: MC *regresses*" in shown
    assert "11 | Doom Breaker | Sent back ten years." in shown
    assert "22 | Kubera | Gods and more gods." in shown
    assert built.title == "MC *regresses*"
    assert [(i.manhwa.anilist_id, i.hook) for i in built.items] == [
        (11, "Ten years back!"),
        (22, "Gods and more gods."),
    ]
    assert built.accent == "#43c9e4"
    assert built.hashtags == "#manhwa"
    assert built.created_at == NOW
    assert built.id.startswith(NOW.astimezone().strftime("%Y%m%d") + "-")
    assert tools.posts.get(built.id) == built
    assert len(slides) == 4


def test_build_cancelled_saves_nothing(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: None))
    assert _build(tools) is None
    assert tools.posts.list() == []


def test_build_bad_draft_keeps_text_for_edit(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: "title: T\n999 | nope | x\n"))
    with pytest.raises(
        DraftError, match=r"999 is not one of .* fix with: manhwatok edit \d{8}-[0-9a-f]{4}"
    ):
        _build(tools)
    [saved] = tools.posts.list()
    assert saved.is_unfinished
    assert saved.candidates == CANDIDATES
    assert tools.posts.load_draft(saved.id) == "title: T\n999 | nope | x\n"
    assert tools.renderer.calls == []


def test_build_no_matches(tmp_path):
    with pytest.raises(ManhwatokError, match="no matches"):
        _build(make_tools(tmp_path), results=[])


def test_build_rejects_bad_accent_before_searching(tmp_path):
    editor = ScriptedEditor(lambda text: text)
    with pytest.raises(ManhwatokError, match="accent must look like #43c9e4"):
        _build(make_tools(tmp_path, editor=editor), accent="cyan")
    assert editor.shown == []


# --- edit --------------------------------------------------------------------------------


def test_edit_reopens_current_post_and_rerenders(tmp_path):
    editor = ScriptedEditor(lambda text: text.replace("Hook 2", "Better hook"))
    tools = make_tools(tmp_path, editor=editor)
    tools.posts.save(post())
    slides = edit_post("20260914-a3f9", tools)
    assert "2 | Title 2 | Hook 2" in editor.shown[0]
    assert tools.posts.get("20260914-a3f9").items[1].hook == "Better hook"
    assert len(slides) == 5


def test_edit_resumes_saved_broken_draft_and_clears_it(tmp_path):
    editor = ScriptedEditor(lambda text: "title: Fixed\n1 | Title 1 | ok\n")
    tools = make_tools(tmp_path, editor=editor)
    tools.posts.save(post(items=[], candidates=[manhwa(anilist_id=1, title="Title 1")]))
    tools.posts.save_draft("20260914-a3f9", "title: T\n999 | nope | x\n")
    edit_post("20260914-a3f9", tools)
    assert editor.shown[0] == "title: T\n999 | nope | x\n"
    assert tools.posts.load_draft("20260914-a3f9") is None
    assert tools.posts.get("20260914-a3f9").title == "Fixed"


def test_edit_can_bring_back_a_dropped_candidate(tmp_path):
    def restore(text):
        return text.replace("# 9 | Dropped | ", "9 | Dropped | ")

    extra = manhwa(anilist_id=9, title="Dropped", description="Was cut. More.")
    tools = make_tools(tmp_path, editor=ScriptedEditor(restore), covers=FakeCovers({}))
    p = post()
    tools.posts.save(p.model_copy(update={"candidates": p.candidates + [extra]}))
    edit_post("20260914-a3f9", tools)
    assert [i.manhwa.anilist_id for i in tools.posts.get("20260914-a3f9").items] == [1, 2, 3, 9]


def test_edit_no_changes(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: None))
    tools.posts.save(post())
    assert edit_post("20260914-a3f9", tools) is None
    assert tools.renderer.calls == []


def test_edit_bad_draft_is_saved(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: "title: T\n"))
    tools.posts.save(post())
    with pytest.raises(DraftError, match="run `manhwatok edit 20260914-a3f9` again"):
        edit_post("20260914-a3f9", tools)
    assert tools.posts.load_draft("20260914-a3f9") == "title: T\n"
    assert tools.posts.get("20260914-a3f9") == post()
