from datetime import datetime, timezone

import pytest

from manhwatok.app.build_post import build_post, create_post
from manhwatok.app.edit_post import edit_post
from manhwatok.domain.account import Account
from manhwatok.domain.models import ArtStyle
from manhwatok.domain.errors import DraftError, InvalidName, ManhwatokError, StorageError
from manhwatok.domain.post import (
    DEFAULT_ACCENT,
    DEFAULT_CTA_FOLLOW,
    DEFAULT_CTA_TITLE,
    DEFAULT_HASHTAGS,
    MAX_ITEMS,
    PostItem,
)
from tests.unit.fakes import FakeCovers, ScriptedEditor, make_tools, manhwa, post

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
CANDIDATES = [
    manhwa(anilist_id=11, title="Doom Breaker", description="Sent back ten years. More."),
    manhwa(anilist_id=22, title="Kubera", description="Gods and more gods. More."),
]
ACCOUNT = Account(
    handle="reads",
    hashtags="#reads",
    accent="#ff00aa",
    cta_title="Seen *these*?",
    cta_follow="More tomorrow",
    art=ArtStyle.BACKGROUND,
)


# --- create_post (pure) --------------------------------------------------------------------


def _create(account=None, hashtags=None, accent=None, art=None):
    items = [PostItem(manhwa=CANDIDATES[0], hook="h")]
    return create_post(
        "20260914-a3f9", NOW, CANDIDATES, "T", items, account, hashtags, accent, art
    )


def test_create_post_without_account_uses_defaults():
    p = _create()
    assert (p.id, p.created_at, p.title, p.candidates) == ("20260914-a3f9", NOW, "T", CANDIDATES)
    assert p.account is None
    assert (p.hashtags, p.accent) == (DEFAULT_HASHTAGS, DEFAULT_ACCENT)
    assert (p.cta_title, p.cta_follow) == (DEFAULT_CTA_TITLE, DEFAULT_CTA_FOLLOW)
    assert p.art is ArtStyle.NONE


def test_create_post_takes_style_and_cta_from_the_account():
    p = _create(ACCOUNT)
    assert p.account == "reads"
    assert (p.hashtags, p.accent) == ("#reads", "#ff00aa")
    assert (p.cta_title, p.cta_follow) == ("Seen *these*?", "More tomorrow")
    assert p.art is ArtStyle.BACKGROUND  # the account's default


def test_create_post_overrides_beat_the_account():
    p = _create(ACCOUNT, hashtags="#once", accent="#ABCDEF")
    assert (p.hashtags, p.accent) == ("#once", "#abcdef")
    assert p.cta_title == "Seen *these*?"


def test_create_post_art_override_beats_the_account():
    assert _create(ACCOUNT, art=ArtStyle.NONE).art is ArtStyle.NONE
    assert _create(art=ArtStyle.BACKGROUND).art is ArtStyle.BACKGROUND


def test_create_post_rejects_a_bad_accent():
    with pytest.raises(InvalidName, match="accent must look like #43c9e4"):
        _create(accent="cyan")


# --- build -------------------------------------------------------------------------------


def _build(tools, title="MC *regresses*", accent="#43C9E4", results=CANDIDATES, account=None):
    return build_post(lambda: results, title, account, "#manhwa", accent, tools, now=NOW)


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


def test_build_accepts_unchanged_draft_saves_and_renders(tmp_path):
    editor = ScriptedEditor(lambda text: text)
    tools = make_tools(tmp_path, editor=editor)
    built, slides = _build(tools)
    assert built.title == "MC *regresses*"
    assert [i.manhwa.anilist_id for i in built.items] == [11, 22]
    assert tools.posts.get(built.id) == built
    assert len(slides) == 4


def test_build_empty_draft_cancels_and_saves_nothing(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: ""))
    assert _build(tools) is None
    assert tools.posts.list() == []


def test_build_comment_only_draft_cancels_and_saves_nothing(tmp_path):
    respond = lambda text: "\n".join("# " + line for line in text.splitlines()) + "\n"
    tools = make_tools(tmp_path, editor=ScriptedEditor(respond))
    assert _build(tools) is None
    assert tools.posts.list() == []


def test_build_prefills_at_most_max_items(tmp_path):
    many = [
        manhwa(anilist_id=i, title=f"T{i}", description="d.") for i in range(1, 41)
    ]
    editor = ScriptedEditor(lambda text: text)
    tools = make_tools(tmp_path, editor=editor)
    built, _ = _build(tools, results=many)
    assert len(built.items) == MAX_ITEMS
    assert built.candidates == many


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
    searched = []

    def find():
        searched.append(True)
        return CANDIDATES

    editor = ScriptedEditor(lambda text: text)
    with pytest.raises(InvalidName, match="accent must look like #43c9e4"):
        build_post(find, "T", None, None, "cyan", make_tools(tmp_path, editor=editor), now=NOW)
    assert searched == []
    assert editor.shown == []


def test_build_for_an_account(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: text))
    built, _ = build_post(lambda: CANDIDATES, "T", ACCOUNT, None, None, tools, now=NOW)
    assert built.account == "reads"
    assert (built.hashtags, built.accent, built.cta_follow) == (
        "#reads",
        "#ff00aa",
        "More tomorrow",
    )
    assert tools.posts.get(built.id) == built


def test_build_bad_draft_for_an_account_keeps_the_account(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: "title: T\n"))
    with pytest.raises(DraftError):
        _build(tools, account=ACCOUNT)
    [saved] = tools.posts.list()
    assert saved.account == "reads"
    assert saved.is_unfinished


@pytest.mark.parametrize(
    "draft", ["title: T\n11 | Doom Breaker | h\n", "title: T\n999 | bad | x\n"], ids=["ok", "bad"]
)
def test_build_gives_back_its_reserved_folder_when_saving_fails(tmp_path, monkeypatch, draft):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: draft))

    def disk_full(post):
        raise StorageError(f"could not save post {post.id}: disk full")

    monkeypatch.setattr(tools.posts, "save", disk_full)
    with pytest.raises(StorageError, match="disk full"):
        _build(tools)
    assert list((tmp_path / "posts").iterdir()) == []


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


def test_edit_unchanged_text_means_no_changes(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: text))
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
