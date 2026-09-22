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
DRAFT = "20260915-0003"


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


def _posts(app):
    """The rows of the table that are posts, headings left out."""
    return [r for r in _rows(app) if not r[1].startswith("──")]


def _details(app) -> str:
    return str(app.query_one("#details").render())


def test_lists_posts_grouped_by_account(tmp_path):
    """One heading per account, its posts under it, newest first; the accountless last."""
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        assert _rows(app) == [
            ["", "── @reads ──", "", "", "", "", "", ""],
            ["", NEW, "@reads", "Manhwa where the MC regresses", "rendered", "-", "-", "5"],
            ["", "── no account ──", "", "", "", "", "", ""],
            ["", OLD, "-", "Manhwa where the MC regresses", "not rendered", "-", "-", "5"],
        ]

    run_app(ctx, scenario)


def test_the_scheduled_column_shows_the_day_and_time_in_the_accounts_zone(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.store.accounts.add(Account(handle="reads"))
    ctx.store.accounts.add(Account(handle="seoul", timezone="Asia/Seoul"))
    at = datetime(2026, 9, 17, 17, 0, tzinfo=timezone.utc)  # Thu 19:00 in Paris
    ctx.tools.posts.save(post(id="20260916-0001", account="reads", scheduled_at=at))
    ctx.tools.posts.save(post(id="20260916-0002", account="seoul", scheduled_at=at))
    ctx.tools.posts.save(post(id="20260916-0003", account="gone", scheduled_at=at))
    ctx.tools.posts.save(post(id="20260916-0004", scheduled_at=at))

    async def scenario(app, pilot):
        assert {r[1]: r[5] for r in _posts(app)} == {
            "20260916-0001": "Thu 19:00",
            "20260916-0002": "Fri 02:00",
            "20260916-0003": "Thu 19:00",  # an account since removed: Paris time
            "20260916-0004": "Thu 19:00",
        }

    run_app(ctx, scenario)


def test_the_sent_column_shows_the_day_it_went_out(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.store.accounts.add(Account(handle="seoul", timezone="Asia/Seoul"))
    at = datetime(2026, 9, 17, 17, 0, tzinfo=timezone.utc)  # 18 Sep in Seoul
    ctx.tools.posts.save(post(id="20260916-0001", account="seoul", sent_at=at))
    ctx.tools.posts.save(post(id="20260916-0002", sent_at=at))
    ctx.tools.posts.save(post(id="20260916-0003"))

    async def scenario(app, pilot):
        assert {r[1]: r[6] for r in _posts(app)} == {
            "20260916-0001": "18 Sep",
            "20260916-0002": "17 Sep",  # no account: Paris time
            "20260916-0003": "-",
        }

    run_app(ctx, scenario)


def test_the_cursor_skips_the_headings(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        pane = app.query_one(PostsPane)
        assert pane.current_id == NEW  # starts on a post, not on its heading
        await pilot.press("down")
        assert pane.current_id == OLD  # stepped over "── no account ──"
        await pilot.press("up")
        assert pane.current_id == NEW
        await pilot.press("up")
        assert pane.current_id == NEW  # nowhere above it but a heading


def test_a_heading_row_is_no_post(tmp_path):
    """Whatever lands on a heading, the actions must refuse rather than act on a neighbour."""
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        table = app.query_one(PostTable)
        table.move_cursor(row=0)  # the heading
        await pilot.pause()
        assert app.query_one(PostsPane).current is None
        await pilot.press("x")
        assert "no post selected" in notes(app)

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
        assert _rows(app)[1][3] == "The Ending [/] Twist"
        table = app.query_one(PostTable)
        rendered = str(table._get_row_renderables(1).cells[3])
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
        assert [r[1] for r in _rows(app)] == ["── @reads ──", NEW]
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert [r[1] for r in _rows(app)] == ["── @reads ──", NEW, "── no account ──", OLD]

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
        await wait_for(pilot, lambda: _rows(app)[3][4] == "rendered")
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
        assert _rows(app)[1][4] == "exported"
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
        kept_rows = ["── @reads ──", NEW, "── no account ──", OLD]
        assert [r[1] for r in _rows(app)] == (kept_rows if kept else ["── no account ──", OLD])

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
        await wait_for(pilot, lambda: _rows(app)[3][4] == "rendered")
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


def _chapter_post(ctx, post_id=OLD):
    from PIL import Image

    from tests.unit.fakes import chapter_part, chapter_post as make

    folder = ctx.tools.posts.folder(post_id)
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for n in (1, 2):
        name = f"panel-{n:03d}.png"
        Image.new("RGB", (27, 48), (30 * n, 60, 90)).save(folder / name)
        names.append(name)
    saved = make(id=post_id, account="reads", chapter=chapter_part(panels=names, to_panel=2))
    ctx.tools.posts.save(saved)
    return saved


def test_a_chapter_post_appears_under_its_account_like_any_other(tmp_path):
    ctx = make_ctx(tmp_path)
    _chapter_post(ctx, post_id=NEW)

    async def scenario(app, pilot):
        assert [r[1] for r in _rows(app)] == ["── @reads ──", NEW]
        assert "Chapter 12 · part 1/2 · 2 panels" in _details(app)
        assert "no picks yet" not in _details(app)

    run_app(ctx, scenario)


@pytest.mark.parametrize(("key", "why"), [("e", "picks"), ("a", "panels"), ("c", "cover")])
def test_actions_that_make_no_sense_for_a_chapter_post_say_so(tmp_path, key, why):
    ctx = make_ctx(tmp_path)
    _chapter_post(ctx, post_id=NEW)

    async def scenario(app, pilot):
        await pilot.press(key)
        await pilot.pause()
        assert any("is a chapter post" in note and why in note for note in notes(app))

    run_app(ctx, scenario)


def test_rendering_a_chapter_post_from_the_posts_pane(tmp_path):
    ctx = make_ctx(tmp_path)
    post = _chapter_post(ctx, post_id=NEW)

    async def scenario(app, pilot):
        await pilot.press("r")
        await wait_for(pilot, lambda: f"post {NEW} · {post.slide_count} slides" in notes(app))

    run_app(ctx, scenario)


# --- marks and bulk actions ---------------------------------------------------------------

MARK = "●"


def _marks(app):
    return [r[0] for r in _rows(app)]


def _summary(app) -> str:
    """A bulk run's closing line: the last notification it shows."""
    return notes(app)[-1]


def test_space_marks_and_unmarks_the_post_under_the_cursor(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        pane = app.query_one(PostsPane)
        await pilot.press("space")
        assert pane.marked == {NEW}
        assert _marks(app) == ["", MARK, "", ""]
        await pilot.press("down", "space")
        assert pane.marked == {NEW, OLD}
        assert _marks(app) == ["", MARK, "", MARK]
        await pilot.press("space")
        assert pane.marked == {NEW}
        assert _marks(app) == ["", MARK, "", ""]
        await pilot.press("escape")
        assert pane.marked == set()
        assert _marks(app) == ["", "", "", ""]

    run_app(ctx, scenario)


def test_a_heading_row_can_never_be_marked(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        table = app.query_one(PostTable)
        table.move_cursor(row=0)  # the heading
        await pilot.pause()
        await pilot.press("space")
        assert app.query_one(PostsPane).marked == set()
        assert "no post selected" in notes(app)

    run_app(ctx, scenario)


def test_ctrl_a_marks_every_post_shown_and_the_filter_drops_the_rest(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        pane = app.query_one(PostsPane)
        await pilot.press("ctrl+a")
        assert pane.marked == {NEW, OLD}
        assert _marks(app) == ["", MARK, "", MARK]
        await pilot.press("f")  # show only @reads: OLD leaves the list, and its mark with it
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()
        assert pane.marked == {NEW}
        assert _marks(app) == ["", MARK]

    run_app(ctx, scenario)


def _three_posts(ctx):
    """_two_posts plus DRAFT, a post with no picks: its render and export both fail."""
    _two_posts(ctx)
    made = datetime(2026, 9, 15, tzinfo=timezone.utc)
    ctx.tools.posts.save(post(id=DRAFT, items=[], created_at=made))


def test_r_renders_every_marked_post_and_says_what_failed(tmp_path):
    ctx = make_ctx(tmp_path)
    _three_posts(ctx)

    async def scenario(app, pilot):
        await pilot.press("ctrl+a", "r")
        await wait_for(pilot, lambda: "failed:" in notes(app)[-1])
        assert notes(app)[0] == "rendering 3 posts…"
        assert f"post {OLD} · 5 slides" in notes(app)  # the failure didn't stop it
        assert _summary(app) == (
            f"rendered 2, 1 failed: {DRAFT} post {DRAFT} has no items "
            f"— fix with: manhwatok edit {DRAFT}"
        )
        assert [r[4] for r in _posts(app)] == ["rendered", "draft", "rendered"]
        assert not app.rendering  # a failure must not leave the app stuck
        await pilot.press("escape", "down", "down", "r")  # and the actions still work after it
        await wait_for(pilot, lambda: f"post {OLD} · 5 slides" in notes(app)[-2:])

    run_app(ctx, scenario)


def test_x_exports_every_marked_post(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        await pilot.press("ctrl+a", "x")
        await wait_for(pilot, lambda: "failed:" in notes(app)[-1])
        assert notes(app)[0] == "exporting 2 posts…"
        assert f"exported → {tmp_path / 'exports' / NEW}" in notes(app)
        assert _summary(app).startswith(
            f"exported 1, 1 failed: {OLD} post {OLD} has no up-to-date slides"
        )
        assert [r[4] for r in _posts(app)] == ["exported", "not rendered"]

    run_app(ctx, scenario)


def test_without_marks_the_bulk_keys_act_on_the_highlighted_post_alone(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)

    async def scenario(app, pilot):
        await pilot.press("x")
        assert f"exported → {tmp_path / 'exports' / NEW}" in notes(app)
        assert not any(n.startswith("exporting ") for n in notes(app))

    run_app(ctx, scenario)


def test_the_other_actions_are_refused_while_a_bulk_run_is_going(tmp_path):
    ctx = make_ctx(tmp_path)
    _two_posts(ctx)
    release = threading.Event()
    render = ctx.tools.renderer.render

    def slow(*args):
        release.wait(5)
        return render(*args)

    ctx.tools.renderer.render = slow

    async def scenario(app, pilot):
        try:
            await pilot.press("ctrl+a", "r")
            await wait_for(pilot, lambda: app.rendering)
            assert notes(app)[0] == "rendering 2 posts…"
            await pilot.press("d")
            assert notes(app).count("still rendering — try again when it's done") == 1
            assert app.screen_stack == [app.screen_stack[0]]  # no ConfirmModal pushed
            await pilot.press("u")
            assert notes(app).count("still rendering — try again when it's done") == 2
            assert not app.browser_open
        finally:
            release.set()
        await wait_for(pilot, lambda: not app.rendering)

    run_app(ctx, scenario)
