import threading
from datetime import datetime, timezone

import pytest

pytest.importorskip("textual")

from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.models import Visibility  # noqa: E402
from manhwatok.domain.theme import Theme  # noqa: E402
from manhwatok.tui.screens.posts import PostsPane  # noqa: E402
from manhwatok.tui.screens.queue import QueuePane, QueueTable  # noqa: E402
from manhwatok.tui.widgets.dialogs import ChoiceModal, ConfirmModal  # noqa: E402
from tests.tui.helpers import make_ctx, notes, run_app, wait_for  # noqa: E402
from tests.unit.fakes import FakeMetadata, FakeUploader, manhwa, post  # noqa: E402

# The app's clock: Wednesday 16 September 2026, 14:00 in Paris.
THU = datetime(2026, 9, 17, 17, 0, tzinfo=timezone.utc)  # 19:00 in Paris
MON = datetime(2026, 9, 21, 17, 0, tzinfo=timezone.utc)
SAT = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)  # 12:00 in Paris, not a slot
LAST_MON = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)
ON_THU, OFF_SAT, LATE, SENT = "20260916-0001", "20260916-0002", "20260915-0003", "20260915-0004"
TITLE = "Manhwa where the MC regresses"
PICKS = [manhwa(anilist_id=i, title=f"Title {i}", description=f"Hook {i}.") for i in (1, 2, 3)]
ISEKAI = Theme(name="isekai", tags=["Isekai"], title="Manhwa where the MC is *reborn*")


def _plan(ctx):
    """@reads (Paris, thu and mon 19:00) with a post on thursday, one off the slots on saturday
    and one overdue since last monday; @seoul (fri 09:00 Seoul time) with nothing yet."""
    ctx.store.accounts.add(Account(handle="reads", slots=["thu 19:00", "mon 19:00"]))
    ctx.store.accounts.add(Account(handle="seoul", slots=["fri 09:00"], timezone="Asia/Seoul"))
    posts = ctx.tools.posts
    posts.save(post(id=ON_THU, account="reads", scheduled_at=THU))
    posts.save(post(id=OFF_SAT, account="reads", scheduled_at=SAT))
    posts.save(post(id=LATE, account="reads", scheduled_at=LAST_MON))
    posts.save(post(id=SENT, account="reads", scheduled_at=LAST_MON, sent_at=LAST_MON))


def _rows(app):
    table = app.query_one(QueueTable)
    return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


def _hint(app) -> str:
    return str(app.query_one("#queue-hint").render())


async def _open(app, pilot):
    await pilot.press("5")
    await pilot.pause()
    return app.query_one(QueuePane)


async def _select(pilot, pane, key: str):
    table = pane.query_one(QueueTable)
    table.move_cursor(row=table.get_row_index(key))
    await pilot.pause()


def test_the_week_by_day_with_overdue_posts_first(tmp_path):
    ctx = make_ctx(tmp_path)
    _plan(ctx)

    async def scenario(app, pilot):
        pane = await _open(app, pilot)
        assert app.query_one("#tabs").active == "queue"
        assert _rows(app) == [
            ["── overdue ──", "", "", "", "", ""],
            ["Mon 14 Sep 19:00", "@reads", LATE, TITLE, "not rendered", "overdue"],
            ["── Thu 17 Sep ──", "", "", "", "", ""],
            ["19:00", "@reads", ON_THU, TITLE, "not rendered", ""],
            ["── Fri 18 Sep ──", "", "", "", "", ""],
            ["09:00", "@seoul", "-", "-", "empty", ""],
            ["── Sat 19 Sep ──", "", "", "", "", ""],
            ["12:00", "@reads", OFF_SAT, TITLE, "not rendered", "not a slot"],
            ["── Mon 21 Sep ──", "", "", "", "", ""],
            ["19:00", "@reads", "-", "-", "empty", ""],
        ]
        assert pane.current is not None and pane.current.post.id == LATE  # not the heading
        await pilot.press("down")
        assert pane.current.post.id == ON_THU  # stepped over the day heading
        assert _hint(app) == ""
        shown = {
            key: active.binding.description
            for key, active in app.active_bindings.items()
            if active.binding.show
        }
        assert {k: shown.get(k) for k in ("enter", "f", "F", "m", "x", "r")} == {
            "enter": "Open post",
            "f": "Fill account",
            "F": "Fill all",
            "m": "Move",
            "x": "Unschedule",
            "r": "Refresh",
        }

    run_app(ctx, scenario)


def test_without_slots_the_queue_says_how_to_add_them(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.store.accounts.add(Account(handle="reads"))

    async def scenario(app, pilot):
        await _open(app, pilot)
        assert _rows(app) == []
        hint = _hint(app)
        assert "no account has slots yet" in hint
        assert "Accounts tab (3)" in hint
        assert 'manhwatok account set @reads --slots "mon 19:00"' in hint
        await pilot.press("f")
        assert "no slot selected" in notes(app)

    run_app(ctx, scenario)


def test_the_queue_picks_up_changes_on_r_and_when_shown_again(tmp_path):
    ctx = make_ctx(tmp_path)
    _plan(ctx)

    async def scenario(app, pilot):
        await _open(app, pilot)
        ctx.tools.posts.save(post(id="20260916-0009", account="seoul", scheduled_at=THU))
        await pilot.press("r")
        await pilot.pause()
        assert ["19:00", "@reads", ON_THU, TITLE, "not rendered", ""] in _rows(app)
        assert ["02:00", "@seoul", "20260916-0009", TITLE, "not rendered", "not a slot"] in _rows(
            app
        )
        await pilot.press("1")
        await pilot.pause()
        ctx.tools.posts.save(post(id="20260916-0010", account="reads", scheduled_at=MON))
        await pilot.press("5")
        await pilot.pause()
        assert ["19:00", "@reads", "20260916-0010", TITLE, "not rendered", ""] in _rows(app)

    run_app(ctx, scenario)


def test_enter_opens_the_post_in_the_posts_tab(tmp_path):
    ctx = make_ctx(tmp_path)
    _plan(ctx)

    async def scenario(app, pilot):
        posts = app.query_one(PostsPane)
        posts.account_filter = "seoul"  # hides the post: opening it shows every account again
        pane = await _open(app, pilot)
        await _select(pilot, pane, f"post:{OFF_SAT}")
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#tabs").active == "posts"
        assert posts.current_id == OFF_SAT
        assert posts.account_filter is None

    run_app(ctx, scenario)


def test_enter_on_an_empty_slot_says_so(tmp_path):
    ctx = make_ctx(tmp_path)
    _plan(ctx)

    async def scenario(app, pilot):
        pane = await _open(app, pilot)
        await _select(pilot, pane, pane.row_keys()[-1])
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#tabs").active == "queue"
        assert "no post in that slot — press f to fill it" in notes(app)

    run_app(ctx, scenario)


def test_move_a_post_to_one_of_its_accounts_empty_slots(tmp_path):
    ctx = make_ctx(tmp_path)
    _plan(ctx)

    async def scenario(app, pilot):
        pane = await _open(app, pilot)
        await _select(pilot, pane, f"post:{ON_THU}")
        await pilot.press("m")
        await wait_for(pilot, lambda: isinstance(app.screen, ChoiceModal))
        assert app.screen.prompt == f"Move post {ON_THU} (@reads) to"
        [(label, value)] = app.screen.choices
        assert label == "Mon 21 Sep 19:00"
        assert datetime.fromisoformat(value) == MON
        await pilot.press("enter")
        await wait_for(pilot, lambda: not isinstance(app.screen, ChoiceModal))
        assert f"post {ON_THU} moved to Mon 21 Sep 19:00" in notes(app)
        assert ["19:00", "@reads", "-", "-", "empty", ""] == _rows(app)[3]  # thursday freed
        assert ["19:00", "@reads", ON_THU, TITLE, "not rendered", ""] in _rows(app)
        assert pane.current.post.id == ON_THU  # the cursor follows the post

    run_app(ctx, scenario)
    assert ctx.tools.posts.get(ON_THU).scheduled_at.astimezone(timezone.utc) == MON


def test_move_the_overdue_post_or_cancel(tmp_path):
    ctx = make_ctx(tmp_path)
    _plan(ctx)

    async def scenario(app, pilot):
        pane = await _open(app, pilot)
        await _select(pilot, pane, f"post:{LATE}")
        await pilot.press("m")
        await wait_for(pilot, lambda: isinstance(app.screen, ChoiceModal))
        await pilot.press("escape")
        await pilot.pause()

    run_app(ctx, scenario)
    assert ctx.tools.posts.get(LATE).scheduled_at == LAST_MON


def test_move_needs_a_post_and_an_empty_slot(tmp_path):
    ctx = make_ctx(tmp_path)
    _plan(ctx)
    ctx.tools.posts.save(post(id="20260916-0005", account="reads", scheduled_at=MON))

    async def scenario(app, pilot):
        pane = await _open(app, pilot)
        await _select(pilot, pane, pane.row_keys()[5])  # @seoul's empty friday
        await pilot.press("m")
        assert "no post in that slot — press f to fill it" in notes(app)
        await _select(pilot, pane, f"post:{ON_THU}")
        await pilot.press("m")
        await pilot.pause()
        assert not isinstance(app.screen, ChoiceModal)
        assert "@reads has no empty slot in the next 7 days" in notes(app)

    run_app(ctx, scenario)


def test_clear_a_posts_schedule_keeps_the_post(tmp_path):
    ctx = make_ctx(tmp_path)
    _plan(ctx)

    async def scenario(app, pilot):
        pane = await _open(app, pilot)
        await _select(pilot, pane, f"post:{OFF_SAT}")
        await pilot.press("x")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        question = str(app.screen.query_one("#question").render())
        assert question == f"Unschedule post {OFF_SAT}? The post is kept."
        await pilot.press("n")
        await pilot.pause()
        assert ctx.tools.posts.get(OFF_SAT).scheduled_at is not None
        await pilot.press("x")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.press("y")
        await wait_for(pilot, lambda: f"post {OFF_SAT} is no longer scheduled" in notes(app))
        assert all(r[2] != OFF_SAT for r in _rows(app))

    run_app(ctx, scenario)
    assert ctx.tools.posts.get(OFF_SAT).scheduled_at is None


def _filling(tmp_path):
    ctx = make_ctx(tmp_path, metadata=FakeMetadata(results=PICKS))
    ctx.store.themes.add(ISEKAI)
    return ctx


def test_f_fills_the_selected_accounts_empty_slots(tmp_path):
    ctx = _filling(tmp_path)
    ctx.store.accounts.add(
        Account(handle="reads", slots=["thu 19:00", "mon 19:00"], rotation=["theme:isekai"])
    )
    ctx.store.accounts.add(
        Account(handle="seoul", slots=["fri 09:00"], rotation=["theme:isekai"])
    )
    ctx.tools.posts.save(post(id=ON_THU, account="reads", scheduled_at=THU))

    async def scenario(app, pilot):
        pane = await _open(app, pilot)
        await _select(pilot, pane, pane.row_keys()[-1])  # @reads's empty monday
        await pilot.press("f")
        await wait_for(pilot, lambda: "@reads: 1 post made and scheduled" in notes(app))
        assert "filling @reads's empty slots of the next 7 days…" in notes(app)
        [made] = [p for p in ctx.tools.posts.list() if p.id != ON_THU]
        made_note = f"Mon 21 Sep 19:00 · @reads · post {made.id} · "
        assert any(n.startswith(made_note) for n in notes(app))
        row = _rows(app)[-1]
        assert row[:3] == ["19:00", "@reads", made.id] and row[4] == "rendered"
        assert ["09:00", "@seoul", "-", "-", "empty", ""] in _rows(app)  # not this account
        await pilot.press("f")
        await wait_for(
            pilot, lambda: "every slot of @reads in the next 7 days has a post" in notes(app)
        )

    run_app(ctx, scenario)
    assert len(ctx.tools.posts.list()) == 2


def test_capital_f_fills_every_account_with_slots_and_reports_failures(tmp_path):
    ctx = _filling(tmp_path)
    ctx.store.accounts.add(Account(handle="aaa", slots=["thu 19:00"]))  # no rotation
    ctx.store.accounts.add(Account(handle="reads", slots=["thu 19:00"], rotation=["theme:isekai"]))
    ctx.store.accounts.add(Account(handle="quiet", rotation=["theme:isekai"]))  # no slots

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("F")
        await wait_for(pilot, lambda: "@reads: 1 post made and scheduled" in notes(app))
        assert any(n.startswith("@aaa: no rotation") for n in notes(app))
        assert "filling the empty slots of 2 accounts for the next 7 days…" in notes(app)
        await wait_for(pilot, lambda: not app.rendering)
        assert [r[1] for r in _rows(app) if r[4] == "rendered"] == ["@reads"]

    run_app(ctx, scenario)
    assert [p.account for p in ctx.tools.posts.list()] == ["reads"]


def test_fill_move_and_clear_wait_for_a_render(tmp_path):
    ctx = _filling(tmp_path)
    _plan(ctx)
    release = threading.Event()

    def slow(tools):
        release.wait(5)

    async def scenario(app, pilot):
        try:
            pane = await _open(app, pilot)
            assert app.start_render(slow, lambda _: None)
            await wait_for(pilot, lambda: app.rendering)
            await _select(pilot, pane, f"post:{ON_THU}")
            for key in ("f", "F", "m", "x"):
                await pilot.press(key)
                await pilot.pause()
                assert not isinstance(app.screen, (ChoiceModal, ConfirmModal))
            assert notes(app).count("still rendering — try again when it's done") == 4
        finally:
            release.set()
        await wait_for(pilot, lambda: not app.rendering)

    run_app(ctx, scenario)
    assert len(ctx.tools.posts.list()) == 4  # nothing made
    assert ctx.tools.posts.get(ON_THU).scheduled_at == THU


# --- uploading from the queue ----------------------------------------------------------------


def _ready(tmp_path, uploader):
    """@reads with a rendered post in its thursday slot, and a browser that answers."""
    from manhwatok.app.render_post import render_post

    ctx = make_ctx(tmp_path, uploader=uploader)
    ctx.store.accounts.add(
        Account(handle="reads", slots=["thu 19:00"], visibility=Visibility.FRIENDS)
    )
    ctx.tools.posts.save(post(id=ON_THU, account="reads", scheduled_at=THU))
    render_post(ON_THU, ctx.tools)
    return ctx


def test_u_uploads_the_selected_post_with_its_slot_as_the_schedule(tmp_path):
    from manhwatok.ports.uploader import UploadReport

    uploader = FakeUploader(UploadReport(True, True, [], titled=True, scheduled_at=THU))
    ctx = _ready(tmp_path, uploader)

    async def scenario(app, pilot):
        pane = await _open(app, pilot)
        await _select(pilot, pane, f"post:{ON_THU}")
        await pilot.press("u")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        assert str(app.screen.query_one("#question").render()) == "Scheduled on @reads?"
        await pilot.press("y")
        await wait_for(pilot, lambda: f"recorded post {ON_THU} as sent" in _log(app))
        await pilot.press("escape")
        await pilot.pause()
        assert [r[4] for r in _rows(app) if r[2] == ON_THU] == ["sent"]

    run_app(ctx, scenario)
    assert uploader.uploads[0][6] == THU  # TikTok's own schedule gets the slot
    assert uploader.uploads[0][7] is Visibility.FRIENDS  # the account's own choice
    assert ctx.tools.posts.get(ON_THU).tiktok_scheduled_at == THU


def test_u_on_an_empty_slot_says_to_fill_it_first(tmp_path):
    uploader = FakeUploader()
    ctx = make_ctx(tmp_path, uploader=uploader)
    ctx.store.accounts.add(Account(handle="reads", slots=["thu 19:00"]))

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("u")
        await pilot.pause()
        assert "no post in that slot — press f to fill it" in notes(app)

    run_app(ctx, scenario)
    assert uploader.events == []


def test_u_is_refused_while_another_browser_is_open(tmp_path):
    release = threading.Event()
    uploader = FakeUploader()
    ctx = _ready(tmp_path, uploader)

    async def scenario(app, pilot):
        pane = await _open(app, pilot)
        await _select(pilot, pane, f"post:{ON_THU}")
        assert app.start_browser(lambda: release.wait(5))
        await wait_for(pilot, lambda: app.browser_open)
        try:
            await pilot.press("u")
            await pilot.pause()
            assert "a browser is already open — finish there first" in notes(app)
        finally:
            release.set()
        await wait_for(pilot, lambda: not app.browser_open)

    run_app(ctx, scenario)
    assert uploader.events == []


def _log(app) -> list[str]:
    return list(app.screen.query_one("Log").lines)
