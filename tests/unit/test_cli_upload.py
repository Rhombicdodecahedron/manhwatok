import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import typer
from typer.testing import CliRunner

from manhwatok.app.login_account import quit_shortcut
from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app import container
from manhwatok.app.render_post import render_post
from manhwatok.cli import app
from manhwatok.domain.account import Account
from manhwatok.domain.errors import NotLoggedIn
from manhwatok.domain.models import Visibility
from manhwatok.ports.uploader import UploadReport
from tests.unit.fakes import FakeUploader, make_tools, post

runner = CliRunner()
POST_ID = "20260914-a3f9"
INSTALL = "error: upload needs: uv sync --extra upload"


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path))


def _browser(monkeypatch, **kwargs) -> FakeUploader:
    fake = FakeUploader(**kwargs)
    monkeypatch.setattr(container, "build_uploader", lambda settings: fake)
    return fake


def _store(tmp_path) -> SqliteStore:
    return SqliteStore(tmp_path / "manhwatok.db")


def _account_post(tmp_path, render=True, **fields):
    """Account @reads and a post of it (rendered with placeholder slides) in the data dir."""
    with _store(tmp_path) as store:
        store.accounts.add(Account(handle="reads"))
    tools = make_tools(tmp_path)
    tools.posts.save(post(**{"account": "reads", **fields}))
    if render:
        render_post(POST_ID, tools)
    return tools.posts


def test_upload_then_yes_records_the_post_as_sent(tmp_path, monkeypatch):
    posts = _account_post(tmp_path)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID], input="y\n")
    assert result.exit_code == 0, result.output
    assert "attached 5 slides\ntyped the title\ntyped the description\n" in result.output
    assert "Posted on @reads? [y/N]" in result.output
    assert result.output.endswith(f"recorded post {POST_ID} as sent\n")
    assert browser.events == ["upload", "close"]
    assert browser.uploads[0][0] == "reads"
    assert browser.uploads[0][2:] == (
        "Manhwa where the MC regresses",
        "1. Title 1\n2. Title 2\n3. Title 3\n\n#manhwa #manhwarecommendation #webtoon "
        "#manhwatiktok",
        None,  # the account has no sounds: nothing asked
        False,  # no --debug
        None,  # not scheduled: the post has no time of its own
        Visibility.EVERYONE,  # neither the post nor the account asks for anything else
    )
    assert posts.get(POST_ID).sent_at is not None
    with _store(tmp_path) as store:
        assert store.history.recent("reads", posts.get(POST_ID).sent_at) == {1, 2, 3}


@pytest.mark.parametrize("answer", ["n\n", "\n", ""])  # no, just Enter, end of input
def test_upload_without_a_yes_records_nothing(tmp_path, monkeypatch, answer):
    posts = _account_post(tmp_path)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID], input=answer)
    assert result.exit_code == 0, result.output
    assert result.output.endswith("nothing recorded\n")
    assert browser.events == ["upload", "close"]
    assert posts.get(POST_ID).sent_at is None


def test_ctrl_c_at_the_question_records_nothing(tmp_path, monkeypatch):
    posts = _account_post(tmp_path)
    browser = _browser(monkeypatch)

    def ctrl_c(*args, **kwargs):
        raise typer.Abort()  # what typer.confirm raises on Ctrl-C

    monkeypatch.setattr(typer, "confirm", ctrl_c)
    result = runner.invoke(app, ["upload", POST_ID])
    assert result.exit_code == 0, result.output
    assert result.output.endswith("nothing recorded\n")
    assert browser.events == ["upload", "close"]
    assert posts.get(POST_ID).sent_at is None


def test_ctrl_c_while_the_browser_works_records_nothing(tmp_path, monkeypatch):
    posts = _account_post(tmp_path)
    browser = _browser(monkeypatch, error=KeyboardInterrupt())
    result = runner.invoke(app, ["upload", POST_ID])
    assert result.exit_code == 130
    assert result.output.endswith("\nnothing recorded\n")
    assert "Traceback" not in result.output
    assert browser.events == ["upload", "close"]
    assert posts.get(POST_ID).sent_at is None


def test_upload_problems_come_before_the_question(tmp_path, monkeypatch):
    _account_post(tmp_path)
    problem = "caption box not found — paste caption.txt yourself"
    browser = _browser(monkeypatch, report=UploadReport(True, False, [problem]))
    result = runner.invoke(app, ["upload", POST_ID, "--debug"], input="n\n")
    assert result.exit_code == 0, result.output
    assert result.output.index(problem) < result.output.index("Posted on @reads?")
    assert browser.uploads[0][5] is True


def test_upload_not_logged_in(tmp_path, monkeypatch):
    _account_post(tmp_path)
    error = NotLoggedIn("@reads is not logged in — run: manhwatok login @reads")
    browser = _browser(monkeypatch, error=error)
    result = runner.invoke(app, ["upload", POST_ID])
    assert result.exit_code == 1
    assert "error: @reads is not logged in — run: manhwatok login @reads" in result.output
    assert browser.events == ["upload", "close"]


def test_upload_needs_an_account_post(tmp_path, monkeypatch):
    browser = _browser(monkeypatch)
    _account_post(tmp_path, account=None)
    result = runner.invoke(app, ["upload", POST_ID])
    assert result.exit_code == 1
    assert f"error: post {POST_ID} has no account — build it with --account" in result.output
    result = runner.invoke(app, ["upload", "20260914-ffff"])
    assert result.exit_code == 1
    assert "error: no post 20260914-ffff" in result.output
    assert browser.events == []


def test_upload_before_render(tmp_path, monkeypatch):
    _browser(monkeypatch)
    _account_post(tmp_path, render=False)
    result = runner.invoke(app, ["upload", POST_ID])
    assert result.exit_code == 1
    assert f"run: manhwatok render {POST_ID}" in result.output


def test_login_opens_the_accounts_browser(tmp_path, monkeypatch):
    with _store(tmp_path) as store:
        store.accounts.add(Account(handle="reads"))
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["login", "@Reads"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith(
        f"Log in to @reads in the Chrome window, then quit that Chrome ({quit_shortcut()}).\n"
    )
    assert "browser closed" in result.output
    assert browser.logins == ["reads"]
    assert browser.events == ["login", "close"]


def test_ctrl_c_during_login_closes_the_browser(tmp_path, monkeypatch):
    with _store(tmp_path) as store:
        store.accounts.add(Account(handle="reads"))
    browser = _browser(monkeypatch, error=KeyboardInterrupt())
    result = runner.invoke(app, ["login", "reads"])
    assert result.exit_code == 130
    assert result.output.endswith("\nstopped — browser closed\n")
    assert browser.events == ["login", "close"]


def test_login_unknown_account(monkeypatch):
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["login", "ghost"])
    assert result.exit_code == 1
    assert "error: no account @ghost" in result.output
    assert browser.events == []


def test_without_the_upload_extra_both_commands_say_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright", None)  # as if the extra weren't installed
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    _account_post(tmp_path)
    for args in (["login", "reads"], ["upload", POST_ID]):
        result = runner.invoke(app, args)
        assert result.exit_code == 1
        assert INSTALL in result.output


def test_help_lists_login_and_upload():
    out = runner.invoke(app, ["--help"]).output
    assert "login" in out and "upload" in out


def _account_with_sounds(tmp_path):
    with _store(tmp_path) as store:
        store.accounts.update(Account(handle="reads", sounds=["solo leveling", "dark aria"]))


@pytest.mark.parametrize(
    ("answers", "expected"),
    [("2\n", "dark aria"), ("\n", "solo leveling"), ("0\n", None), ("7\n1\n", "solo leveling")],
    ids=["second", "enter takes the first", "none", "out of range asks again"],
)
def test_upload_asks_which_sound(tmp_path, monkeypatch, answers, expected):
    _account_post(tmp_path)
    _account_with_sounds(tmp_path)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID], input=answers + "n\n")
    assert result.exit_code == 0, result.output
    assert result.output.startswith(
        f"post {POST_ID} → @reads, posting now\n"
        "Sound for this post:\n  1. solo leveling\n  2. dark aria\n  0. no sound\nPick [1]: "
    )
    assert browser.uploads[0][4] == expected


def test_upload_sound_options_skip_the_question(tmp_path, monkeypatch):
    _account_post(tmp_path)
    _account_with_sounds(tmp_path)
    browser = _browser(monkeypatch)
    for args, expected in [(["--sound", "night drive"], "night drive"), (["--no-sound"], None)]:
        result = runner.invoke(app, ["upload", POST_ID, *args], input="n\n")
        assert result.exit_code == 0, result.output
        assert "Sound for this post" not in result.output
        assert browser.uploads[-1][4] == expected


def test_upload_says_which_sound_was_added(tmp_path, monkeypatch):
    _account_post(tmp_path)
    report = UploadReport(True, True, [], titled=True, sound="SOLO LEVELING (00:59 · RaijinLofi)")
    _browser(monkeypatch, report=report)
    result = runner.invoke(app, ["upload", POST_ID, "--sound", "solo leveling"], input="n\n")
    assert "added the sound SOLO LEVELING (00:59 · RaijinLofi)\n" in result.output


def test_upload_then_yes_marks_a_chapter_posts_part_published(tmp_path, monkeypatch):
    from PIL import Image

    from manhwatok.domain.chapter import PartRecord
    from tests.unit.fakes import chapter_part, chapter_post

    with _store(tmp_path) as store:
        store.accounts.add(Account(handle="reads"))
    tools = make_tools(tmp_path)
    folder = tools.posts.folder(POST_ID)
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (27, 48), (30, 60, 90)).save(folder / "panel-001.png")
    tools.posts.save(
        chapter_post(
            chapter=chapter_part(panels=["panel-001.png"], to_panel=1), account="reads"
        )
    )
    render_post(POST_ID, tools)
    with _store(tmp_path) as store:
        store.chapters.record_part(
            PartRecord(
                anilist_id=1, number="12", language="en", part=1, parts=2, post_id=POST_ID,
                built_at=tools.posts.get(POST_ID).created_at,
            )
        )
    _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID], input="y\n")
    assert result.exit_code == 0, result.output
    with _store(tmp_path) as store:
        assert store.chapters.parts(1)[0].published_at is not None


# --- TikTok's own schedule -------------------------------------------------------------------


def _soon(**delta) -> datetime:
    """A time relative to the real clock: the command reads its own."""
    return datetime.now(timezone.utc) + timedelta(**delta)


def _scheduled_browser(monkeypatch, at):
    return _browser(
        monkeypatch, report=UploadReport(True, True, [], titled=True, scheduled_at=at)
    )


def test_a_post_planned_for_later_is_scheduled_on_tiktok(tmp_path, monkeypatch):
    at = _soon(hours=2).replace(second=0, microsecond=0)
    posts = _account_post(tmp_path, scheduled_at=at)
    browser = _scheduled_browser(monkeypatch, at)
    result = runner.invoke(app, ["upload", POST_ID], input="y\n")
    assert result.exit_code == 0, result.output
    local = at.astimezone(ZoneInfo("Europe/Paris"))
    assert result.output.startswith(
        f"post {POST_ID} → @reads, scheduled for {local:%a %d %b %H:%M} (Europe/Paris)\n"
    )
    assert browser.uploads[0][6] == at
    assert "Scheduled on @reads? [y/N]" in result.output
    assert posts.get(POST_ID).tiktok_scheduled_at == at


@pytest.mark.parametrize(
    "fields",
    [{}, {"scheduled_at": _soon(minutes=5)}, {"scheduled_at": _soon(days=11)}],
    ids=["unscheduled", "too soon", "too far off"],
)
def test_a_post_tiktok_wouldnt_schedule_goes_out_now(tmp_path, monkeypatch, fields):
    _account_post(tmp_path, **fields)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID], input="n\n")
    assert result.exit_code == 0, result.output
    assert result.output.startswith(f"post {POST_ID} → @reads, posting now\n")
    assert browser.uploads[0][6] is None
    assert "Posted on @reads? [y/N]" in result.output


def test_at_takes_a_time_in_the_accounts_zone(tmp_path, monkeypatch):
    _account_post(tmp_path)
    browser = _browser(monkeypatch)
    when = _soon(hours=3).astimezone(ZoneInfo("Europe/Paris"))
    result = runner.invoke(
        app, ["upload", POST_ID, "--at", f"{when:%Y-%m-%d %H:%M}"], input="n\n"
    )
    assert result.exit_code == 0, result.output
    assert browser.uploads[0][6] == when.replace(second=0, microsecond=0)


def test_at_slot_takes_the_posts_own_time(tmp_path, monkeypatch):
    at = _soon(days=2).replace(second=0, microsecond=0)
    _account_post(tmp_path, scheduled_at=at)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID, "--at", "slot"], input="n\n")
    assert result.exit_code == 0, result.output
    assert browser.uploads[0][6] == at


def test_at_slot_without_a_time_says_so(tmp_path, monkeypatch):
    _account_post(tmp_path)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID, "--at", "slot"])
    assert result.exit_code == 1
    assert f"error: post {POST_ID} has no time of its own" in result.output
    assert browser.events == []


def test_no_schedule_uploads_a_planned_post_now(tmp_path, monkeypatch):
    _account_post(tmp_path, scheduled_at=_soon(hours=2))
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID, "--no-schedule"], input="n\n")
    assert result.exit_code == 0, result.output
    assert browser.uploads[0][6] is None


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--at", "2020-01-01 10:00"], "already past"),
        (["--at", "not a time"], "YYYY-MM-DD HH:MM"),
        (["--at", "slot", "--no-schedule"], "give --at or --no-schedule, not both"),
    ],
    ids=["past", "nonsense", "both"],
)
def test_a_time_tiktok_wont_take_never_opens_the_browser(tmp_path, monkeypatch, args, message):
    _account_post(tmp_path, scheduled_at=_soon(hours=2))
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID, *args])
    assert result.exit_code == 1
    assert message in result.output
    assert browser.events == []


def test_at_too_far_off_is_refused_with_tiktoks_limit(tmp_path, monkeypatch):
    _account_post(tmp_path)
    browser = _browser(monkeypatch)
    when = _soon(days=12).astimezone(ZoneInfo("Europe/Paris"))
    result = runner.invoke(app, ["upload", POST_ID, "--at", f"{when:%Y-%m-%d %H:%M}"])
    assert result.exit_code == 1
    assert "at most 10 days ahead" in result.output
    assert browser.events == []


# --- a sound that needs no question ----------------------------------------------------------


def test_a_default_sound_is_used_without_asking(tmp_path, monkeypatch):
    _account_post(tmp_path)
    with _store(tmp_path) as store:
        store.accounts.update(
            Account(handle="reads", sounds=["dark aria"], default_sound="night drive")
        )
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Sound for this post" not in result.output
    assert browser.uploads[0][4] == "night drive"


def test_ask_sound_brings_the_question_back(tmp_path, monkeypatch):
    _account_post(tmp_path)
    with _store(tmp_path) as store:
        store.accounts.update(
            Account(handle="reads", sounds=["dark aria"], default_sound="night drive")
        )
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID, "--ask-sound"], input="2\nn\n")
    assert result.exit_code == 0, result.output
    assert "  1. night drive\n  2. dark aria\n" in result.output
    assert browser.uploads[0][4] == "dark aria"


# --- a sound picked at random ----------------------------------------------------------------


def _last_sound(monkeypatch) -> None:
    """random.choice, made predictable: the last of whatever it is offered."""
    import random

    monkeypatch.setattr(random, "choice", lambda sounds: sounds[-1])


def test_random_sound_picks_one_without_asking_and_says_so(tmp_path, monkeypatch):
    _account_post(tmp_path)
    _account_with_sounds(tmp_path)
    _last_sound(monkeypatch)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID, "--random-sound"], input="n\n")
    assert result.exit_code == 0, result.output
    assert result.output.startswith(
        f'post {POST_ID} → @reads, posting now, sound: "dark aria" (picked at random)\n'
    )
    assert "Sound for this post" not in result.output
    assert browser.uploads[0][4] == "dark aria"


def test_the_accounts_random_sound_asks_nothing_either(tmp_path, monkeypatch):
    _account_post(tmp_path)
    with _store(tmp_path) as store:
        store.accounts.update(
            Account(handle="reads", sounds=["solo leveling", "dark aria"], random_sound=True)
        )
    _last_sound(monkeypatch)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID], input="n\n")
    assert result.exit_code == 0, result.output
    assert '(picked at random)' in result.output
    assert browser.uploads[0][4] == "dark aria"


def test_random_sound_without_any_sound_to_pick_asks_nothing_and_adds_none(
    tmp_path, monkeypatch
):
    _account_post(tmp_path)  # @reads has no sounds at all
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID, "--random-sound"], input="n\n")
    assert result.exit_code == 0, result.output
    assert result.output.startswith(f"post {POST_ID} → @reads, posting now\n")
    assert browser.uploads[0][4] is None


def test_ask_sound_beats_random_sound_from_the_command_line(tmp_path, monkeypatch):
    _account_post(tmp_path)
    _account_with_sounds(tmp_path)
    browser = _browser(monkeypatch)
    result = runner.invoke(
        app, ["upload", POST_ID, "--random-sound", "--ask-sound"], input="2\nn\n"
    )
    assert result.exit_code == 0, result.output
    assert "picked at random" not in result.output
    assert "  1. solo leveling\n  2. dark aria\n" in result.output
    assert browser.uploads[0][4] == "dark aria"


def test_a_sound_and_no_sound_together_are_refused(tmp_path, monkeypatch):
    _account_post(tmp_path)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID, "--sound", "night drive", "--no-sound"])
    assert result.exit_code == 1
    assert "give --sound or --no-sound, not both" in result.output
    assert browser.events == []


# --- who can see the post --------------------------------------------------------------------


def _visible(tmp_path, who):
    with _store(tmp_path) as store:
        store.accounts.update(Account(handle="reads", visibility=who))


def test_upload_uses_the_accounts_visibility_and_says_so(tmp_path, monkeypatch):
    _account_post(tmp_path)
    _visible(tmp_path, Visibility.FRIENDS)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID], input="n\n")
    assert result.exit_code == 0, result.output
    assert result.output.startswith(
        f"post {POST_ID} → @reads, visible to friends, posting now\n"
    )
    assert browser.uploads[0][7] is Visibility.FRIENDS


def test_a_posts_own_visibility_beats_its_accounts(tmp_path, monkeypatch):
    _account_post(tmp_path, visibility=Visibility.PRIVATE)
    _visible(tmp_path, Visibility.FRIENDS)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID], input="n\n")
    assert result.exit_code == 0, result.output
    assert result.output.startswith(
        f"post {POST_ID} → @reads, visible to you alone, posting now\n"
    )
    assert browser.uploads[0][7] is Visibility.PRIVATE


def test_upload_visibility_beats_both_and_changes_no_post(tmp_path, monkeypatch):
    posts = _account_post(tmp_path, visibility=Visibility.PRIVATE)
    _visible(tmp_path, Visibility.FRIENDS)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID, "--visibility", "everyone"], input="n\n")
    assert result.exit_code == 0, result.output
    assert result.output.startswith(f"post {POST_ID} → @reads, posting now\n")
    assert browser.uploads[0][7] is Visibility.EVERYONE
    assert posts.get(POST_ID).visibility is Visibility.PRIVATE  # a one-off, nothing saved


def test_the_line_says_both_who_sees_it_and_when(tmp_path, monkeypatch):
    at = _soon(hours=2).replace(second=0, microsecond=0)
    _account_post(tmp_path, scheduled_at=at, visibility=Visibility.FRIENDS)
    _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID], input="n\n")
    local = at.astimezone(ZoneInfo("Europe/Paris"))
    assert result.output.startswith(
        f"post {POST_ID} → @reads, visible to friends, scheduled for "
        f"{local:%a %d %b %H:%M} (Europe/Paris)\n"
    )


def test_upload_says_what_tiktok_ended_up_showing(tmp_path, monkeypatch):
    _account_post(tmp_path)
    report = UploadReport(True, True, [], titled=True, visibility=Visibility.PRIVATE)
    _browser(monkeypatch, report=report)
    result = runner.invoke(app, ["upload", POST_ID, "--visibility", "private"], input="n\n")
    assert "TikTok will show it to you alone\n" in result.output


def test_a_visibility_tiktok_doesnt_have_never_opens_the_browser(tmp_path, monkeypatch):
    _account_post(tmp_path)
    browser = _browser(monkeypatch)
    result = runner.invoke(app, ["upload", POST_ID, "--visibility", "nobody"])
    assert result.exit_code == 2
    assert browser.events == []


def test_the_visibility_command_sets_and_clears_a_posts_own(tmp_path):
    posts = _account_post(tmp_path, render=False)
    result = runner.invoke(app, ["visibility", POST_ID, "friends"])
    assert result.exit_code == 0, result.output
    assert result.output == f"post {POST_ID} is visible to friends\n"
    assert posts.get(POST_ID).visibility is Visibility.FRIENDS
    result = runner.invoke(app, ["visibility", POST_ID, "--clear"])
    assert result.exit_code == 0, result.output
    assert result.output == f"post {POST_ID} follows its account's choice\n"
    assert posts.get(POST_ID).visibility is None


def test_the_visibility_command_wants_one_of_a_choice_or_clear(tmp_path):
    _account_post(tmp_path, render=False)
    assert runner.invoke(app, ["visibility", POST_ID]).exit_code == 1
    assert runner.invoke(app, ["visibility", POST_ID, "friends", "--clear"]).exit_code == 1
    assert runner.invoke(app, ["visibility", POST_ID, "nobody"]).exit_code == 2
    result = runner.invoke(app, ["visibility", "20260914-ffff", "friends"])
    assert result.exit_code == 1 and "error: no post 20260914-ffff" in result.output
