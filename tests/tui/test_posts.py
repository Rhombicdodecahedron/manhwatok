from datetime import datetime, timezone

import pytest

pytest.importorskip("textual")

from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.tui.screens.posts import PostsPane, PostTable  # noqa: E402
from manhwatok.tui.widgets.slide_preview import SlidePreview  # noqa: E402
from tests.tui.helpers import Opened, make_ctx, notes, run_app  # noqa: E402
from tests.unit.fakes import post  # noqa: E402

OLD, NEW = "20260913-0001", "20260914-0002"


def _two_posts(ctx):
    """NEW (rendered, @reads, account song) above OLD (not rendered, no account, own song)."""
    ctx.store.accounts.add(Account(handle="reads", song="Acct Song"))
    posts = ctx.tools.posts
    posts.save(post(id=OLD, created_at=datetime(2026, 9, 13, tzinfo=timezone.utc), song="Own"))
    posts.save(post(id=NEW, account="reads", created_at=datetime(2026, 9, 14, tzinfo=timezone.utc)))
    render_post(NEW, ctx.tools)


def _rows(app):
    table = app.query_one(PostTable)
    return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


def _details(app) -> str:
    return str(app.query_one("#details").render())


def test_lists_posts_with_status_and_song(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        assert _rows(app) == [
            [NEW, "@reads", "Manhwa where the MC regresses", "rendered", "Acct Song", "5"],
            [OLD, "-", "Manhwa where the MC regresses", "not rendered", "Own", "5"],
        ]

    run_app(ctx, scenario)


def test_the_preview_flips_through_the_highlighted_posts_slides(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)
    folder = ctx.tools.posts.folder(NEW)

    async def scenario(app, pilot):
        preview = app.query_one(SlidePreview)
        assert preview.current == folder / "01.png"
        assert str(app.query_one("#slide-counter").render()) == "◀ 1/5 ▶"
        assert "Song: Acct Song\n" in _details(app)
        await pilot.press("right", "right")
        assert preview.current == folder / "03.png"
        await pilot.press("left", "left", "left")
        assert preview.current == folder / "05.png"
        await pilot.press("o")
        assert opened == [folder / "05.png"]
        await pilot.press("down")
        assert preview.current is None
        assert str(app.query_one("#slide-note").render()) == "not rendered — press r"
        assert "Song: Own (this post's)" in _details(app)
        assert "Caption (not rendered)" in _details(app)
        await pilot.press("o")
        assert "no slide to open" in notes(app)

    opened = Opened()
    run_app(ctx, scenario, opener=opened)


def test_a_slide_that_isnt_an_image_gets_a_note(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)
    (ctx.tools.posts.folder(NEW) / "01.png").write_bytes(b"not a png")

    async def scenario(app, pilot):
        assert str(app.query_one("#slide-note").render()) == "can't show 01.png"
        assert not app.query_one("#slide-image").display
        await pilot.press("right")
        assert app.query_one("#slide-image").display

    run_app(ctx, scenario)


def test_filter_by_account(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()
        assert [r[0] for r in _rows(app)] == [NEW]
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert [r[0] for r in _rows(app)] == [NEW, OLD]

    run_app(ctx, scenario)


def test_no_posts_yet(tmp_path):
    async def scenario(app, pilot):
        assert _rows(app) == []
        note = str(app.query_one("#slide-note").render())
        assert note == "no posts yet — build one in the Build tab (2)"
        assert app.query_one(PostsPane).current is None

    run_app(make_ctx(tmp_path), scenario)
