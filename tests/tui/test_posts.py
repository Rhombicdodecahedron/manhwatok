import threading
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("textual")

from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.models import ArtStyle, CoverStyle  # noqa: E402
from manhwatok.tui.screens.posts import PostsPane, PostTable  # noqa: E402
from manhwatok.tui.widgets.slide_preview import SlidePreview  # noqa: E402
from tests.tui.helpers import NOW, Opened, make_ctx, notes, run_app, wait_for  # noqa: E402
from tests.unit.fakes import post  # noqa: E402

OLD, NEW = "20260913-0001", "20260914-0002"


def _two_posts(ctx):
    """NEW (rendered, @reads with two sounds) above OLD (not rendered, no account, with its own
    art style and emojis)."""
    ctx.store.accounts.add(Account(handle="reads", sounds=["Dark Aria", "night drive"]))
    posts = ctx.tools.posts
    old = datetime(2026, 9, 13, tzinfo=timezone.utc)
    posts.save(post(id=OLD, created_at=old, art=ArtStyle.BACKGROUND, emojis="🔥📚"))
    new = datetime(2026, 9, 14, tzinfo=timezone.utc)
    posts.save(post(id=NEW, account="reads", created_at=new))
    render_post(NEW, ctx.tools)


def _rows(app):
    table = app.query_one(PostTable)
    return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


def _details(app) -> str:
    return str(app.query_one("#details").render())


def test_lists_posts_with_status(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        assert _rows(app) == [
            [NEW, "@reads", "Manhwa where the MC regresses", "rendered", "5"],
            [OLD, "-", "Manhwa where the MC regresses", "not rendered", "5"],
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
        assert "\nSounds: Dark Aria | night drive\n\nCaption\n" in _details(app)
        await pilot.press("right", "right")
        assert preview.current == folder / "03.png"
        await pilot.press("left", "left", "left")
        assert preview.current == folder / "05.png"
        await pilot.press("o")
        assert opened == [folder / "05.png"]
        await pilot.press("down")
        assert preview.current is None
        assert str(app.query_one("#slide-note").render()) == "not rendered — press r"
        assert "\nSounds: –\nArt: background\nEmojis: 🔥📚\n" in _details(app)
        assert "Caption (not rendered)" in _details(app)
        await pilot.press("o")
        assert "no slide to open" in notes(app)

    opened = Opened()
    run_app(ctx, scenario, opener=opened)


def test_a_bracketed_title_renders_verbatim_in_the_table(tmp_path):
    """A post title with square brackets must not be parsed as Rich markup: it must not crash
    the table, and must not be silently mangled (e.g. an unclosed tag raising MarkupError)."""
    ctx = make_ctx(tmp_path)
    ctx.tools.posts.save(post(title="The Ending [/] Twist"))

    async def scenario(app, pilot):
        assert _rows(app)[0][2] == "The Ending [/] Twist"
        table = app.query_one(PostTable)
        rendered = str(table._get_row_renderables(0).cells[2])
        assert rendered == "The Ending [/] Twist"

    run_app(ctx, scenario)


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


def test_readable_image_rejects_a_decompression_bomb(tmp_path, monkeypatch):
    """A huge (or huge-claiming) image must be treated like any other unreadable slide, not
    crash the preview with an uncaught PIL.Image.DecompressionBombError."""
    from PIL import Image as PILImage

    from manhwatok.tui.widgets.slide_preview import readable_image

    path = tmp_path / "huge.png"
    PILImage.new("RGB", (100, 100)).save(path)
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 1)
    assert readable_image(path) is False


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


def test_details_show_no_sounds_for_a_removed_account(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.tools.posts.save(post(id=NEW, account="gone"))

    async def scenario(app, pilot):
        assert "\nSounds: –\n" in _details(app)
        assert notes(app) == []

    run_app(ctx, scenario)


def test_s_does_nothing_now_that_posts_have_no_song(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen.query_one(PostsPane), PostsPane)
        assert len(app.screen_stack) == 1

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
        await pilot.press("e", "r", "x", "u", "d", "c")
        assert notes(app).count("no post selected") == 6

    run_app(make_ctx(tmp_path), scenario)


def _first_slide_is(ctx, post_id, style):
    folder = ctx.tools.posts.folder(post_id)
    return (folder / "01.png").read_bytes() == (folder / f"cover-{style.value}.png").read_bytes()


def test_cover_swaps_a_rendered_version_into_the_first_slide(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        assert _first_slide_is(ctx, NEW, CoverStyle.FAN)
        await pilot.press("c")
        await pilot.pause()
        labels = [str(o.prompt) for o in app.screen.query_one("OptionList")._options]
        assert labels[0].startswith("fan") and "current" in labels[0]
        await pilot.press("down", "enter")  # quad
        await pilot.pause()
        assert ctx.tools.posts.get(NEW).cover is CoverStyle.QUAD
        assert _first_slide_is(ctx, NEW, CoverStyle.QUAD)
        assert f"post {NEW} · quad cover" in notes(app)
        assert "Cover: quad" in _details(app)

    run_app(ctx, scenario)


def test_cover_of_an_unrendered_post_renders_it_with_that_cover(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        await pilot.press("down", "c")
        await pilot.pause()
        await pilot.press("down", "down", "enter")  # hero
        await wait_for(pilot, lambda: _rows(app)[1][3] == "rendered")
        assert ctx.tools.posts.get(OLD).cover is CoverStyle.HERO
        assert _first_slide_is(ctx, OLD, CoverStyle.HERO)

    run_app(ctx, scenario)


def test_escaping_the_cover_choice_changes_nothing(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        await pilot.press("c")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert ctx.tools.posts.get(NEW).cover is CoverStyle.FAN
        assert "Cover:" not in _details(app)

    run_app(ctx, scenario)
