from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")

from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.domain.account import Account  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import post  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402

OLD, NEW, DRAFT = "20260913-0001", "20260914-0002", "20260915-0003"


def _posts(ctx):
    """NEW (rendered, @reads), OLD (not rendered, no account), DRAFT (no picks, @reads)."""
    ctx.store.accounts.add(Account(handle="reads", sounds=["Dark Aria"]))
    posts = ctx.tools.posts
    posts.save(post(id=OLD, created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    posts.save(post(id=NEW, account="reads", created_at=datetime(2026, 9, 14, tzinfo=timezone.utc)))
    posts.save(post(id=DRAFT, account="reads", items=[],
                    created_at=datetime(2026, 9, 15, tzinfo=timezone.utc)))
    render_post(NEW, ctx.tools)
    return ctx


def _order(html: str) -> list[str]:
    return sorted((OLD, NEW, DRAFT), key=lambda pid: html.find(pid) if pid in html else 10**9)


def test_the_page_lists_posts_newest_first_with_their_status(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        html = client.get("/posts").text
    assert "<html" in html and 'id="posts-table"' in html and 'id="detail"' in html
    assert _order(html) == [DRAFT, NEW, OLD]
    for status in ("draft", "rendered", "not rendered"):
        assert f'<span class="status">{status}</span>' in html


def test_filters_by_account_and_status(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        reads = client.get("/posts/table", params={"account": "reads"}).text
        none = client.get("/posts/table", params={"account": "none"}).text
        rendered = client.get("/posts/table", params={"status": "rendered"}).text
    assert NEW in reads and DRAFT in reads and OLD not in reads
    assert OLD in none and NEW not in none
    assert NEW in rendered and OLD not in rendered and DRAFT not in rendered
    assert "<html" not in reads  # a fragment


def test_no_posts_says_so(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        assert "No posts yet" in client.get("/posts").text


def test_a_selected_post_loads_into_the_detail_pane(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        html = client.get("/posts", params={"post": NEW}).text
    assert f'hx-get="/posts/{NEW}"' in html


def test_the_detail_shows_slides_covers_caption_and_what_tiktok_gets(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        html = client.get(f"/posts/{NEW}").text
    assert 'id="post-detail"' in html and "<html" not in html
    assert html.count("data-slide") == 5  # one per rendered slide
    assert f'src="/files/{NEW}/01.png?v=' in html
    for style in ("fan", "quad", "hero"):
        assert f"/files/{NEW}/cover-{style}.png" in html
    assert 'class="chosen"' in html  # the post's own cover (fan)
    assert "Dark Aria" in html  # the account's sound
    assert "everyone (the account&#39;s)" in html  # HTML-escaped


def test_a_post_without_its_account_still_shows(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    ctx.store.accounts.remove("reads")
    with client_for(ctx) as client:
        response = client.get(f"/posts/{NEW}")
    assert response.status_code == 200
    assert "@reads (removed)" in response.text


def test_a_draft_says_it_has_no_picks(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        html = client.get(f"/posts/{DRAFT}").text
    assert "no picks yet" in html and "data-slide" not in html


def test_a_post_deleted_elsewhere_says_it_is_gone(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        from manhwatok.app.delete_post import delete_post

        delete_post(NEW, ctx.tools.posts)
        response = client.get(f"/posts/{NEW}")
    assert response.status_code == 200
    assert f"Post {NEW} is gone" in response.text


import json  # noqa: E402

from tests.web.helpers import wait_job  # noqa: E402


def _notice(response) -> dict:
    return json.loads(response.headers["HX-Trigger"])["notice"]


def _last_job(client):
    return client.app.state.jobs.recent()[0]


def test_render_runs_in_the_background_and_reports(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        response = client.post(f"/posts/{OLD}/render")
        assert _notice(response) == {"text": f"rendering post {OLD}…", "level": "info"}
        job = wait_job(client, _last_job(client).id)
    assert job.outcome == f"rendered post {OLD}" and not job.failed
    assert job.log == [f"post {OLD} · 5 slides"]
    assert (ctx.tools.posts.folder(OLD) / "01.png").is_file()


def test_rendering_a_draft_ends_with_its_error(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        client.post(f"/posts/{DRAFT}/render")
        job = wait_job(client, _last_job(client).id)
    assert job.failed and job.outcome.startswith(f"error: post {DRAFT} has no items")


def test_a_second_render_waits_its_turn(tmp_path):
    import threading

    from manhwatok.web.jobs import RENDER

    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        release = threading.Event()
        job = client.app.state.jobs.start(
            RENDER, "render post a", lambda io: release.wait(5) and "ok"
        )
        busy = client.post(f"/posts/{OLD}/render")
        export = client.post(f"/posts/{NEW}/export")
        release.set()
        wait_job(client, job.id)
    assert _notice(busy)["level"] == "warning"
    assert _notice(export) == {
        "text": "still rendering — try again when it's done", "level": "warning"
    }


def test_choosing_a_drawn_cover_swaps_it_in(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    hero = ctx.tools.posts.folder(NEW) / "cover-hero.png"
    with client_for(ctx) as client:
        response = client.post(f"/posts/{NEW}/cover", data={"style": "hero"})
    assert _notice(response) == {"text": f"post {NEW} · hero cover", "level": "info"}
    assert (ctx.tools.posts.folder(NEW) / "01.png").read_bytes() == hero.read_bytes()
    assert ctx.tools.posts.get(NEW).cover.value == "hero"
    assert json.loads(response.headers["HX-Trigger"])["changed-posts"] is True


def test_choosing_a_cover_of_an_unrendered_post_renders_it(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        response = client.post(f"/posts/{OLD}/cover", data={"style": "quad"})
        wait_job(client, _last_job(client).id)
    assert _notice(response)["text"] == f"rendering post {OLD} with the quad cover…"
    assert ctx.tools.posts.get(OLD).cover.value == "quad"


def test_visibility_is_set_and_cleared(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        client.post(f"/posts/{NEW}/visibility", data={"visibility": "private"})
        assert ctx.tools.posts.get(NEW).visibility.value == "private"
        response = client.post(f"/posts/{NEW}/visibility", data={"visibility": ""})
        assert ctx.tools.posts.get(NEW).visibility is None
        bad = client.post(f"/posts/{NEW}/visibility", data={"visibility": "martians"})
    assert _notice(response)["text"] == f"post {NEW} · visible to everyone (the account's)"
    assert _notice(bad)["level"] == "error"


def test_export_copies_the_slides(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        response = client.post(f"/posts/{NEW}/export")
    dest = ctx.settings.export_dir / NEW
    assert _notice(response)["text"] == f"exported → {dest}"
    assert (dest / "01.png").is_file()


def test_delete_removes_the_post(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        response = client.post(f"/posts/{OLD}/delete")
        again = client.post(f"/posts/{OLD}/delete")
    assert not ctx.tools.posts.folder(OLD).exists()
    assert _notice(response) == {"text": f"deleted post {OLD}", "level": "info"}
    assert _notice(again)["level"] == "error"


def test_bulk_render_export_and_delete(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        client.post("/posts/bulk", data={"action": "render", "ids": [OLD, NEW]})
        job = wait_job(client, _last_job(client).id)
        exported = client.post("/posts/bulk", data={"action": "export", "ids": [OLD, NEW]})
        deleted = client.post("/posts/bulk", data={"action": "delete", "ids": [OLD, DRAFT]})
        nothing = client.post("/posts/bulk", data={"action": "delete"})
    assert job.outcome == "rendered 2 posts"
    assert job.log == [f"post {OLD} · 5 slides", f"post {NEW} · 5 slides"]
    assert _notice(exported)["text"] == f"exported 2 posts → {ctx.settings.export_dir}"
    assert _notice(deleted)["text"] == "deleted 2 posts"
    assert not ctx.tools.posts.folder(DRAFT).exists() and ctx.tools.posts.folder(NEW).exists()
    assert _notice(nothing) == {"text": "tick some posts first", "level": "warning"}


def test_a_bulk_action_carries_on_past_a_post_that_fails_as_the_tui_does(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        response = client.post("/posts/bulk", data={"action": "export", "ids": [NEW, DRAFT, OLD]})
        client.post("/posts/bulk", data={"action": "render", "ids": [DRAFT, OLD]})
        job = wait_job(client, _last_job(client).id)
    notice = _notice(response)
    assert notice["level"] == "warning"
    assert notice["text"].startswith(
        f"exported 1 post → {ctx.settings.export_dir}, 2 failed: {DRAFT} post {DRAFT} has no items"
    )
    assert f"; {OLD} post {OLD} has no up-to-date slides" in notice["text"]
    # A draft ticked first doesn't stop the rest from rendering.
    assert job.outcome.startswith(f"rendered 1 post, 1 failed: {DRAFT} post {DRAFT} has no items")
    assert job.log[0].startswith(f"post {DRAFT} failed: post {DRAFT} has no items")
    assert job.log[1] == f"post {OLD} · 5 slides"


def test_the_detail_has_the_buttons(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        html = client.get(f"/posts/{NEW}").text
    for action in ("render", "export", "delete"):
        assert f'hx-post="/posts/{NEW}/{action}"' in html
    assert f'hx-post="/posts/{NEW}/visibility"' in html
    assert f'hx-post="/posts/{NEW}/cover"' in html
    assert "hx-confirm" in html  # delete asks first


def test_titles_read_without_their_accent_marks(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    ctx.tools.posts.save(ctx.tools.posts.get(NEW).model_copy(update={"title": "Love *hurts*"}))
    with client_for(ctx) as client:
        table = client.get("/posts/table").text
        detail = client.get(f"/posts/{NEW}").text
    assert "Love hurts" in table and "Love hurts" in detail
    assert "*hurts*" not in table + detail


def test_cover_and_visibility_wait_for_a_running_render(tmp_path):
    """The renderer writes 01.png from the post it read at the start, and a quad render saves
    that post again at the end: a cover or visibility set meanwhile would be lost or torn."""
    import threading

    from manhwatok.web.jobs import RENDER

    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        release = threading.Event()
        job = client.app.state.jobs.start(
            RENDER, "render post a", lambda io: release.wait(5) and "ok"
        )
        cover = client.post(f"/posts/{NEW}/cover", data={"style": "hero"})
        seen = client.post(f"/posts/{NEW}/visibility", data={"visibility": "private"})
        release.set()
        wait_job(client, job.id)
    for response in (cover, seen):
        assert _notice(response) == {
            "text": "still rendering — try again when it's done", "level": "warning"
        }
    assert ctx.tools.posts.get(NEW).cover.value == "fan"
    assert ctx.tools.posts.get(NEW).visibility is None
