from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("textual")

from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.errors import NotLoggedIn  # noqa: E402
from manhwatok.ports.uploader import UploadReport  # noqa: E402
from manhwatok.tui.screens.browser import BrowserScreen  # noqa: E402
from manhwatok.tui.screens.posts import PostTable  # noqa: E402
from manhwatok.tui.widgets.dialogs import ChoiceModal, ConfirmModal  # noqa: E402
from tests.tui.helpers import NOW, make_ctx, notes, run_app, wait_for  # noqa: E402
from tests.unit.fakes import FakeUploader, post  # noqa: E402

PID = "20260914-a3f9"
OTHER = "20260913-b1c2"


def _ctx(tmp_path, uploader, sounds=(), **fields):
    ctx = make_ctx(tmp_path, uploader=uploader)
    ctx.store.accounts.add(Account(handle="reads", sounds=list(sounds)))
    ctx.tools.posts.save(post(**{"account": "reads", **fields}))
    render_post(PID, ctx.tools)
    return ctx


def _log(app) -> list[str]:
    return list(app.screen.query_one("Log").lines)


async def _upload_until_asked(app, pilot, key="u"):
    await pilot.press(key)
    await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
    assert str(app.screen.query_one("#question").render()) == "Posted on @reads?"


def test_yes_records_the_post_as_sent(tmp_path):
    uploader = FakeUploader(UploadReport(True, False, ["caption box not found"]))
    ctx = _ctx(tmp_path, uploader)

    async def scenario(app, pilot):
        await _upload_until_asked(app, pilot)
        await pilot.press("y")
        await wait_for(pilot, lambda: "done — press escape to go back" in _log(app))
        log = _log(app)
        assert log[:3] == [
            "attached 5 slides",
            "caption box not found",
            f"slides and caption.txt: {ctx.tools.posts.folder(PID)}",
        ]
        assert f"recorded post {PID} as sent" in log
        await pilot.press("escape")
        await pilot.pause()
        table = app.query_one(PostTable)
        assert str(table.get_row_at(1)[4]) == "sent"  # row 0 is the account heading

    run_app(ctx, scenario)
    assert uploader.events == ["upload", "close"]
    # no sounds to pick from, no debug, and the post has no time of its own to schedule
    assert uploader.uploads[0][4:] == (None, False, None)
    assert ctx.tools.posts.get(PID).sent_at == NOW
    assert ctx.store.history.recent("reads", NOW) == {1, 2, 3}


def test_no_records_nothing_and_debug_is_passed_on(tmp_path):
    uploader = FakeUploader()
    ctx = _ctx(tmp_path, uploader)

    async def scenario(app, pilot):
        await _upload_until_asked(app, pilot, key="U")
        assert app.screen_stack[-2].heading == f"Upload post {PID} (debug)"
        await pilot.press("n")
        await wait_for(pilot, lambda: "nothing recorded" in _log(app))

    run_app(ctx, scenario)
    assert uploader.uploads[0][5] is True
    assert ctx.tools.posts.get(PID).sent_at is None
    assert ctx.store.history.recent("reads", NOW) == set()


def test_escape_waits_until_the_question_is_answered(tmp_path):
    ctx = _ctx(tmp_path, FakeUploader())

    async def scenario(app, pilot):
        await _upload_until_asked(app, pilot)
        await pilot.press("escape")  # answers the question: no
        await wait_for(pilot, lambda: isinstance(app.screen, BrowserScreen))
        await wait_for(pilot, lambda: not app.screen.running)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, BrowserScreen)

    run_app(ctx, scenario)


def test_escape_while_the_browser_works_says_to_finish_first(tmp_path):
    import threading

    release = threading.Event()

    class Slow(FakeUploader):
        def upload(self, *args):
            release.wait(5)
            return super().upload(*args)

    ctx = _ctx(tmp_path, Slow())

    async def scenario(app, pilot):
        await pilot.press("u")
        await wait_for(pilot, lambda: isinstance(app.screen, BrowserScreen) and app.browser_open)
        await pilot.press("escape")
        assert isinstance(app.screen, BrowserScreen)
        assert any(n.startswith("the browser is still open") for n in notes(app))
        release.set()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.press("n")

    run_app(ctx, scenario)


def test_errors_are_shown_in_the_log_and_as_a_notification(tmp_path):
    uploader = FakeUploader(
        error=NotLoggedIn("@reads is not logged in — run: manhwatok login @reads")
    )
    ctx = _ctx(tmp_path, uploader)

    async def scenario(app, pilot):
        await pilot.press("u")
        await wait_for(pilot, lambda: "done — press escape to go back" in _log(app))
        assert "error: @reads is not logged in — run: manhwatok login @reads" in _log(app)
        assert "@reads is not logged in — run: manhwatok login @reads" in notes(app)

    run_app(ctx, scenario)
    assert uploader.events == ["upload", "close"]


def test_a_post_without_an_account_never_opens_the_browser(tmp_path):
    uploader = FakeUploader()
    ctx = _ctx(tmp_path, uploader, account=None)

    async def scenario(app, pilot):
        await pilot.press("u")
        await wait_for(pilot, lambda: "done — press escape to go back" in _log(app))
        assert f"error: post {PID} has no account — build it with --account" in _log(app)

    run_app(ctx, scenario)
    assert uploader.events == []  # checked before any browser was opened


def test_U_uploads_every_marked_post_in_turn(tmp_path):
    """The bulk variant of `U`: one job through the marked posts, a question each, and a
    summary; an answer of "no" records nothing but isn't a failure."""
    uploader = FakeUploader()
    ctx = _ctx(tmp_path, uploader)
    made = datetime(2026, 9, 13, tzinfo=timezone.utc)  # older, so it comes second
    ctx.tools.posts.save(post(id=OTHER, account="reads", created_at=made))
    render_post(OTHER, ctx.tools)

    async def scenario(app, pilot):
        await pilot.press("ctrl+a", "U")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.press("y")
        await wait_for(pilot, lambda: f"post {PID} sent" in notes(app))
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.press("n")
        await wait_for(pilot, lambda: notes(app)[-1].startswith("uploaded "))
        assert notes(app)[0] == "uploading 2 posts…"
        assert notes(app)[-1] == "uploaded 2"
        assert f"post {OTHER} not recorded" in notes(app)

    run_app(ctx, scenario)
    assert uploader.events == ["upload", "close", "upload", "close"]
    assert [u[5] for u in uploader.uploads] == [True, True]  # the debug variant, as single U
    assert ctx.tools.posts.get(PID).sent_at == NOW
    assert ctx.tools.posts.get(OTHER).sent_at is None


# --- picking the sound ------------------------------------------------------------------------

SOUNDS = ("Dark Aria", "night drive")


def _choices(app) -> list[str]:
    options = app.screen.query_one("OptionList")
    return [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)]


@pytest.mark.parametrize(
    "keys, chosen",
    [
        (["down", "enter"], "night drive"),
        (["enter"], "Dark Aria"),
        (["end", "enter"], None),  # "no sound"
        (["escape"], None),
    ],
)
def test_upload_asks_which_sound_and_passes_it_on(tmp_path, keys, chosen):
    found = f"{chosen} · TikTok" if chosen else None
    report = UploadReport(True, True, [], titled=True, sound=found)
    uploader = FakeUploader(report)
    ctx = _ctx(tmp_path, uploader, sounds=SOUNDS)

    async def scenario(app, pilot):
        await pilot.press("u")
        await wait_for(pilot, lambda: isinstance(app.screen, ChoiceModal))
        assert str(app.screen.query_one("Label").render()) == "Sound for @reads"
        assert _choices(app) == ["Dark Aria", "night drive", "no sound"]
        assert uploader.events == []  # asked before the browser opens
        await pilot.press(*keys)
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.press("n")
        await wait_for(pilot, lambda: "nothing recorded" in _log(app))
        added = [line for line in _log(app) if line.startswith("added the sound")]
        assert added == ([f"added the sound {chosen} · TikTok"] if chosen else [])

    run_app(ctx, scenario)
    assert uploader.uploads[0][4] == chosen


def test_sound_names_with_brackets_render_verbatim_and_pass_through(tmp_path):
    """Square brackets in a sound name must not be parsed as Textual markup: they must not
    crash the option list, and must not be silently dropped from what's shown or chosen."""
    tricky = ("Dark Aria [Remix]", "a [/] b")
    report = UploadReport(True, True, [], titled=True, sound="Dark Aria [Remix] · TikTok")
    uploader = FakeUploader(report)
    ctx = _ctx(tmp_path, uploader, sounds=tricky)

    async def scenario(app, pilot):
        await pilot.press("u")
        await wait_for(pilot, lambda: isinstance(app.screen, ChoiceModal))
        assert _choices(app) == ["Dark Aria [Remix]", "a [/] b", "no sound"]
        await pilot.press("enter")  # choose "Dark Aria [Remix]"
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.press("n")
        await wait_for(pilot, lambda: "nothing recorded" in _log(app))

    run_app(ctx, scenario)
    assert uploader.uploads[0][4] == "Dark Aria [Remix]"


def test_quitting_while_the_sound_choice_is_open_cancels_the_upload(tmp_path):
    """Answering the sound question with None because the app is quitting must not fall
    through to a real upload — choose_sound must refuse before upload_post opens the browser."""
    uploader = FakeUploader()
    ctx = _ctx(tmp_path, uploader, sounds=SOUNDS)

    async def scenario(app, pilot):
        await pilot.press("u")
        await wait_for(pilot, lambda: isinstance(app.screen, ChoiceModal))
        await pilot.press("ctrl+q")  # the option list takes plain keys; ctrl+q always quits
        await wait_for(pilot, lambda: not app.is_running)

    run_app(ctx, scenario)
    assert uploader.events == []
    assert ctx.tools.posts.get(PID).sent_at is None


def test_u_fills_in_tiktoks_schedule_from_the_posts_own_slot(tmp_path):
    """As `manhwatok upload` does by default: a post planned for later is scheduled on TikTok,
    and the question then asks about the schedule."""
    at = NOW + timedelta(hours=3)
    report = UploadReport(True, True, [], titled=True, scheduled_at=at)
    uploader = FakeUploader(report)
    ctx = _ctx(tmp_path, uploader, scheduled_at=at)

    async def scenario(app, pilot):
        await pilot.press("u")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        assert str(app.screen.query_one("#question").render()) == "Scheduled on @reads?"
        await pilot.press("y")
        await wait_for(pilot, lambda: "done — press escape to go back" in _log(app))

    run_app(ctx, scenario)
    assert uploader.uploads[0][6] == at
    assert ctx.tools.posts.get(PID).tiktok_scheduled_at == at


def test_a_post_planned_for_too_soon_is_uploaded_as_todays(tmp_path):
    uploader = FakeUploader()
    ctx = _ctx(tmp_path, uploader, scheduled_at=NOW + timedelta(minutes=5))

    async def scenario(app, pilot):
        await _upload_until_asked(app, pilot)
        await pilot.press("n")
        await wait_for(pilot, lambda: "nothing recorded" in _log(app))

    run_app(ctx, scenario)
    assert uploader.uploads[0][6] is None
