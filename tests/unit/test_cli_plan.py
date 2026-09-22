import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from manhwatok import cli
from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.cli import app
from manhwatok.domain.account import Account
from tests.unit.fakes import post
from tests.unit.test_cli_next import _account, _dirs, _ids, wire  # noqa: F401 (fixtures)

runner = CliRunner()
PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)  # Tuesday, 12:00 in Paris
THU = datetime(2026, 9, 24, 19, 0, tzinfo=PARIS)
MON = datetime(2026, 9, 28, 19, 0, tzinfo=PARIS)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW)


def _store(tmp_path) -> SqliteStore:
    return SqliteStore(tmp_path / "data" / "manhwatok.db")


def _ok(args) -> str:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.output


def _err(args) -> str:
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    return result.output


# --- account --slots -------------------------------------------------------------------------


def test_account_slots_are_stored_shown_and_cleared(tmp_path, wire):
    out = _ok(["account", "add", "reads", "--slots", "Mon 19:00, thu 9:30,"])
    with _store(tmp_path) as store:
        assert store.accounts.get("reads").slots == ["mon 19:00", "thu 09:30"]
    assert "  slots         mon 19:00, thu 09:30\n" in out

    out = _ok(["account", "set", "reads", "--slots", ""])
    with _store(tmp_path) as store:
        assert store.accounts.get("reads").slots == []
    assert "  slots         -\n" in out
    assert "  slots         -\n" in _ok(["account", "show", "reads"])


def test_a_bad_slot_is_refused(tmp_path, wire):
    assert "is not a slot" in _err(["account", "add", "reads", "--slots", "monday at 7"])


# --- plan fill -------------------------------------------------------------------------------


def test_plan_fill_makes_a_post_for_each_empty_slot(tmp_path, wire):
    repo, _ = wire
    _account(tmp_path, ["theme:isekai"], slots=["mon 19:00", "thu 19:00"])

    out = _ok(["plan", "fill", "-a", "@reads"])

    first, second = _ids(out)
    assert repo.get(first).scheduled_at == THU and repo.get(second).scheduled_at == MON
    assert f"Thu 24 Sep 19:00  @reads  post {first} · Isekai picks" in out
    assert "manhwatok plan show" in out

    again = _ok(["plan", "fill", "-a", "reads"])
    assert _ids(again) == []
    assert "every slot of @reads in the next 7 days has a post" in again


def test_plan_fill_without_an_account_fills_every_account_with_slots(tmp_path, wire):
    _account(tmp_path, ["theme:isekai"], slots=["thu 19:00"])
    with _store(tmp_path) as store:
        store.accounts.add(Account(handle="idle", rotation=["theme:isekai"]))

    out = _ok(["plan", "fill", "--days", "3"])

    assert len(_ids(out)) == 1 and "@idle" not in out


def test_plan_fill_with_no_slots_anywhere_says_how_to_set_them(tmp_path, wire):
    _account(tmp_path, ["theme:isekai"])
    assert "--slots" in _ok(["plan", "fill"])
    assert "--slots" in _err(["plan", "fill", "-a", "reads"])


def test_plan_fill_keeps_what_it_made_before_a_failure(tmp_path, wire):
    repo, _ = wire
    _account(tmp_path, ["chapter:The Boxer"], slots=["mon 19:00", "thu 19:00"])

    out = _err(["plan", "fill", "-a", "reads"])

    [made] = _ids(out)
    assert repo.get(made).scheduled_at == THU
    assert "error: nothing left to post in @reads's rotation" in out


def test_plan_fill_days_are_capped_at_ten(tmp_path, wire):
    _account(tmp_path, ["theme:isekai"], slots=["mon 19:00"])
    assert "1–10 days" in _err(["plan", "fill", "-a", "reads", "--days", "11"])


# --- plan show -------------------------------------------------------------------------------


def test_plan_show_lists_the_slots_by_day_with_their_posts(tmp_path, wire):
    repo, _ = wire
    _account(tmp_path, ["theme:isekai"], slots=["mon 19:00", "thu 19:00"])
    with _store(tmp_path) as store:
        store.accounts.add(Account(handle="seoul", slots=["thu 09:00"], timezone="Asia/Seoul"))
    repo.save(post(id="20260922-aaaa", account="reads", scheduled_at=THU))
    off = datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)
    repo.save(post(id="20260922-bbbb", account="reads", scheduled_at=off))

    out = _ok(["plan", "show"])

    assert out.splitlines() == [
        "Thu 24 Sep",
        "  09:00  @seoul  — empty",
        "  19:00  @reads  20260922-aaaa  Manhwa where the MC regresses  not rendered",
        "Fri 25 Sep",
        "  10:00  @reads  20260922-bbbb  Manhwa where the MC regresses  not rendered  (not a slot)",
        "Mon 28 Sep",
        "  19:00  @reads  — empty",
    ]


def test_plan_show_for_one_account_and_fewer_days(tmp_path, wire):
    _account(tmp_path, ["theme:isekai"], slots=["mon 19:00", "thu 19:00"])
    with _store(tmp_path) as store:
        store.accounts.add(Account(handle="other", slots=["thu 19:00"]))

    out = _ok(["plan", "show", "-a", "@reads", "--days", "3"])

    assert out.splitlines() == ["Thu 24 Sep", "  19:00  @reads  — empty"]


def test_plan_show_with_nothing_planned_says_how_to_plan(tmp_path, wire):
    _account(tmp_path, ["theme:isekai"])
    assert "--slots" in _ok(["plan", "show"])


# --- schedule --------------------------------------------------------------------------------


def test_schedule_sets_and_clears_a_posts_time(tmp_path, wire):
    repo, _ = wire
    _account(tmp_path, ["theme:isekai"], timezone="Asia/Seoul")
    repo.save(post(account="reads"))

    out = _ok(["schedule", "20260914-a3f9", "2026-09-24 19:00"])
    when = repo.get("20260914-a3f9").scheduled_at
    assert when == datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    assert "post 20260914-a3f9 goes out Thu 24 Sep 2026 19:00 (Asia/Seoul)" in out

    out = _ok(["schedule", "20260914-a3f9", "--clear"])
    assert repo.get("20260914-a3f9").scheduled_at is None
    assert "post 20260914-a3f9 is no longer scheduled" in out


def test_schedule_takes_a_day_and_time_for_the_next_one(tmp_path, wire):
    repo, _ = wire
    repo.save(post())
    _ok(["schedule", "20260914-a3f9", "thu 19:00"])
    assert repo.get("20260914-a3f9").scheduled_at == THU


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "give a time or --clear"),
        (["thu 19:00", "--clear"], "give a time or --clear, not both"),
        (["someday"], "YYYY-MM-DD HH:MM"),
        (["2026-09-01 10:00"], "already past"),
    ],
)
def test_schedule_errors(tmp_path, wire, args, message):
    repo, _ = wire
    repo.save(post())
    assert message in _err(["schedule", "20260914-a3f9", *args])


def test_schedule_an_unknown_post_fails(wire):
    assert "no post 20260101-0000" in _err(["schedule", "20260101-0000", "thu 19:00"])


# --- posts -----------------------------------------------------------------------------------


def test_posts_shows_when_a_post_is_scheduled(tmp_path, wire):
    repo, _ = wire
    repo.save(post(id="20260913-0001", created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    repo.save(post(id="20260914-0002", scheduled_at=THU))

    lines = runner.invoke(app, ["posts"]).output.strip().splitlines()

    local = THU.astimezone().strftime("%Y-%m-%d %H:%M")
    assert re.match(rf"20260914-0002  \S+ \S+  -   5 slides  for {local}  Manhwa", lines[0])
    assert re.match(r"20260913-0001  \S+ \S+  -   5 slides {24}Manhwa", lines[1])
