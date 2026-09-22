from datetime import datetime, timezone

from manhwatok.app.render_post import render_post
from manhwatok.domain.models import ArtStyle
from manhwatok.domain.post import PostItem
from manhwatok.tui.text import caption_text, clip, post_details, post_status
from tests.unit.fakes import make_tools, manhwa, post

WHEN = datetime(2026, 9, 15, tzinfo=timezone.utc)


def test_post_status(tmp_path):
    tools = make_tools(tmp_path)
    posts = tools.posts
    assert post_status(post(items=[]), posts) == "draft"
    posts.save(post())
    assert post_status(post(), posts) == "not rendered"
    render_post("20260914-a3f9", tools)
    assert post_status(post(), posts) == "rendered"
    assert post_status(post(exported_at=WHEN), posts) == "exported"
    assert post_status(post(exported_at=WHEN, sent_at=WHEN), posts) == "sent"


def test_caption_text_prefers_the_rendered_file(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    text, rendered = caption_text(post(), tools.posts)
    assert not rendered and text.startswith("Manhwa where the MC regresses\n\n1. Title 1")
    render_post("20260914-a3f9", tools)
    (tools.posts.folder("20260914-a3f9") / "caption.txt").write_text("edited\n")
    assert caption_text(post(), tools.posts) == ("edited", True)


def test_post_details(tmp_path):
    tools = make_tools(tmp_path)
    text = post_details(post(account="reads"), tools.posts, ["Dark Aria", "night drive"])
    assert text.splitlines()[:4] == [
        "Manhwa where the MC regresses",
        "20260914-a3f9 · @reads · not rendered · 5 slides",
        "",
        "Sounds: Dark Aria | night drive",
    ]
    assert "Art:" not in text and "Emojis:" not in text
    assert "Caption (not rendered)" in text
    assert " 1. Title 1 — ongoing\n    Hook 1" in text
    assert "Sounds: –\n" in post_details(post(), tools.posts, [])


def test_post_details_shows_art_and_emojis_when_set(tmp_path):
    styled = post(art=ArtStyle.BACKGROUND, emojis="🔥📚")
    text = post_details(styled, make_tools(tmp_path).posts, ["S"])
    assert text.splitlines()[3:6] == ["Sounds: S", "Art: background", "Emojis: 🔥📚"]


def test_post_details_shows_the_emojis_auto_picked(tmp_path):
    items = [PostItem(manhwa=manhwa(anilist_id=1, genres=["Romance"]), hook="Hook")]
    auto = post(items=items, emojis="auto")
    text = post_details(auto, make_tools(tmp_path).posts, [])
    assert "Emojis: 💗🌹 (auto)" in text


def test_post_details_of_a_draft(tmp_path):
    text = post_details(post(title="", items=[]), make_tools(tmp_path).posts, [])
    assert text.splitlines()[0] == "(untitled)"
    assert "no account · draft · no picks" in text
    assert text.endswith("no picks yet — press e to pick titles")


def test_clip():
    assert clip("abc", 3) == "abc"
    assert clip("abcd", 3) == "ab…"


def test_post_details_shows_who_can_see_it_only_when_the_post_says(tmp_path):
    from manhwatok.domain.models import Visibility

    posts = make_tools(tmp_path).posts
    assert "Visible to:" not in post_details(post(), posts, [])  # its account decides
    text = post_details(post(visibility=Visibility.PRIVATE), posts, ["S"])
    assert text.splitlines()[3:5] == ["Sounds: S", "Visible to: you alone"]
