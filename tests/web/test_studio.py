import pytest

pytest.importorskip("fastapi")

from tests.tui.helpers import make_ctx  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402


def test_the_slides_font_is_served_for_the_pages(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        response = client.get("/fonts/Montserrat-Variable.ttf")
    assert response.status_code == 200
    assert len(response.content) > 100_000


def test_the_shell_has_the_sidebar_and_the_mode_switch(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        html = client.get("/posts").text
    assert '<nav class="sidebar"' in html
    assert '<a href="/posts" aria-current="page"' in html
    assert '<a href="/new"' in html
    assert 'hx-post="/mode"' in html and 'id="header"' in html


def test_the_stylesheet_uses_the_font_and_the_palette(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        css = client.get("/static/app.css").text
    assert "Montserrat-Variable.ttf" in css
    for token in ("--gutter: #1c1a24", "--paper: #efe9dd", "--accent: #43c9e4"):
        assert token in css


from datetime import datetime, timezone  # noqa: E402

from manhwatok.app.render_post import render_post  # noqa: E402
from tests.unit.fakes import post  # noqa: E402

RENDERED, BARE = "20260914-0002", "20260913-0001"


def _two(ctx):
    ctx.tools.posts.save(post(id=BARE, created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    ctx.tools.posts.save(post(id=RENDERED, created_at=datetime(2026, 9, 14, tzinfo=timezone.utc)))
    render_post(RENDERED, ctx.tools)
    return ctx


def test_posts_are_cards_with_their_cover(tmp_path):
    with client_for(_two(make_ctx(tmp_path))) as client:
        html = client.get("/posts/table").text
    assert html.count('<article class="card') == 2
    assert f'<img src="/files/{RENDERED}/01.png?v=' in html
    assert "Not rendered yet" in html  # the bare post's card
    assert '<span class="dot" data-status="rendered"></span>' in html
    assert f'hx-get="/posts/{RENDERED}"' in html and 'hx-target="#detail"' in html


def test_the_selected_card_is_marked(tmp_path):
    with client_for(_two(make_ctx(tmp_path))) as client:
        html = client.get("/posts/table", params={"selected": BARE}).text
    assert html.count("is-selected") == 1
    card = html[html.index("is-selected"):]
    assert card.index(BARE) < card.index("</article>")


def test_the_viewer_shows_the_first_slide_big_and_all_in_the_filmstrip(tmp_path):
    with client_for(_two(make_ctx(tmp_path))) as client:
        html = client.get(f"/posts/{RENDERED}").text
    stage = html[html.index('class="stage"'):]
    assert f'src="/files/{RENDERED}/01.png?v=' in stage[: stage.index("</div>")]
    assert html.count("data-slide") == 5
    assert html.count('aria-current="true"') == 1


def test_the_detail_takes_the_accounts_accent(tmp_path):
    from manhwatok.domain.account import Account

    ctx = _two(make_ctx(tmp_path))
    ctx.store.accounts.add(Account(handle="reads", accent="#ff5588"))
    ctx.tools.posts.save(ctx.tools.posts.get(RENDERED).model_copy(update={"account": "reads"}))
    with client_for(ctx) as client:
        html = client.get(f"/posts/{RENDERED}").text
    assert 'style="--accent: #ff5588"' in html
