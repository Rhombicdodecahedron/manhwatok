"""The post view helpers live in app/ so the TUI and the web app share them."""

from datetime import datetime, timezone

from manhwatok.app import post_view
from manhwatok.app.render_post import render_post
from manhwatok.tui import text
from tests.unit.fakes import make_tools, post


def test_the_tui_uses_the_shared_helpers():
    for name in ("post_status", "scheduled_text", "sent_text", "caption_text"):
        assert getattr(text, name) is getattr(post_view, name)


def test_post_status_follows_the_post(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(id="20260926-0001"))
    fresh = tools.posts.get("20260926-0001")
    assert post_view.post_status(fresh, tools.posts) == "not rendered"
    render_post(fresh.id, tools)
    assert post_view.post_status(fresh, tools.posts) == "rendered"
    sent = fresh.model_copy(update={"sent_at": datetime(2026, 9, 26, tzinfo=timezone.utc)})
    assert post_view.post_status(sent, tools.posts) == "sent"
