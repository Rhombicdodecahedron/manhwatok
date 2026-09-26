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
