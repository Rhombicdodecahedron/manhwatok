import threading
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("textual")

from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.tui.screens.posts import PostsPane, PostTable  # noqa: E402
from manhwatok.tui.widgets.slide_preview import SlidePreview  # noqa: E402
from tests.tui.helpers import NOW, Opened, make_ctx, notes, run_app, wait_for  # noqa: E402
from tests.unit.fakes import post  # noqa: E402

OLD, NEW = "20260913-0001", "20260914-0002"


def _two_posts(ctx):
    """NEW (rendered, @reads, account song) above OLD (not rendered, no account, own song)."""
    ctx.store.accounts.add(Account(handle="reads", song="Acct Song"))
    posts = ctx.tools.posts
    posts.save(post(id=OLD, created_at=datetime(2026, 9, 13, tzinfo=timezone.utc), song="Own"))
    new = datetime(2026, 9, 14, tzinfo=timezone.utc)
    posts.save(post(id=NEW, account="reads", created_at=new))
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


def test_render_renders_the_highlighted_post(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        await pilot.press("down", "r")
        await wait_for(pilot, lambda: _rows(app)[1][3] == "rendered")
        assert app.query_one(SlidePreview).current == ctx.tools.posts.folder(OLD) / "01.png"
        assert f"post {OLD} · 5 slides" in notes(app)

    run_app(ctx, scenario)


def test_render_of_a_draft_says_what_to_do(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.tools.posts.save(post(items=[]))

    async def scenario(app, pilot):
        await pilot.press("r")
        await wait_for(pilot, lambda: any("has no items" in n for n in notes(app)))

    run_app(ctx, scenario)


def test_export_copies_the_slides_and_records_the_titles(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        await pilot.press("x")
        assert f"exported → {tmp_path / 'exports' / NEW}" in notes(app)
        assert _rows(app)[0][3] == "exported"
        assert ctx.store.history.recent("reads", NOW - timedelta(days=1)) == {1, 2, 3}
        await pilot.press("down", "x")
        assert any(n.startswith(f"post {OLD} has no up-to-date slides") for n in notes(app))

    run_app(ctx, scenario)
    assert len(list((tmp_path / "exports" / NEW).glob("*.png"))) == 5


def test_song_sets_and_clears_the_posts_own_song(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        await pilot.press("s")
        await pilot.pause()
        assert "leave empty for the account's: Acct Song" in str(
            app.screen.query_one("Label").render()
        )
        await pilot.press(*"Mine", "enter")
        await pilot.pause()
        assert ctx.tools.posts.get(NEW).song == "Mine"
        assert _rows(app)[0][4] == "Mine"
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("backspace", "enter")  # the old value is selected: clear it
        await pilot.pause()
        assert ctx.tools.posts.get(NEW).song is None
        assert _rows(app)[0][4] == "Acct Song"
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("x", "escape")
        await pilot.pause()
        assert ctx.tools.posts.get(NEW).song is None

    run_app(ctx, scenario)


@pytest.mark.parametrize("answer, kept", [("y", False), ("n", True)])
def test_delete_asks_first(tmp_path, answer, kept):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        await pilot.press("d")
        await pilot.pause()
        assert str(app.screen.query_one("#question").render()) == f"Delete post {NEW} (5 slides)?"
        await pilot.press(answer)
        await pilot.pause()
        assert [r[0] for r in _rows(app)] == ([NEW, OLD] if kept else [OLD])

    run_app(ctx, scenario)
    assert ctx.tools.posts.folder(NEW).exists() is kept


def test_export_upload_delete_refuse_while_a_render_is_running(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)
    release = threading.Event()

    def slow(tools):
        release.wait(5)
        return "slow"

    async def scenario(app, pilot):
        try:
            assert app.start_render(slow, lambda _: None)
            await wait_for(pilot, lambda: app.rendering)

            await pilot.press("x")
            assert notes(app).count("still rendering — try again when it's done") == 1
            assert not (ctx.settings.export_dir / NEW).exists()

            await pilot.press("u")
            assert notes(app).count("still rendering — try again when it's done") == 2
            assert app.screen_stack == [app.screen_stack[0]]  # no BrowserScreen pushed
            assert not app.browser_open

            await pilot.press("d")
            assert notes(app).count("still rendering — try again when it's done") == 3
            assert app.screen_stack == [app.screen_stack[0]]  # no ConfirmModal pushed
            assert ctx.tools.posts.folder(NEW).exists()
        finally:
            release.set()
        await wait_for(pilot, lambda: not app.rendering)

    run_app(ctx, scenario)


def test_actions_without_a_post_warn(tmp_path):
    async def scenario(app, pilot):
        await pilot.press("r", "x", "s", "d")
        assert notes(app).count("no post selected") == 4

    run_app(make_ctx(tmp_path), scenario)
