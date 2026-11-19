import os
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from manhwatok import cli
from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app import container
from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_post
from manhwatok.cli import app
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.post import PostItem
from manhwatok.ports.uploader import UploadReport
from tests.unit.fakes import FakeCovers, FakeRenderer, FakeUploader, post
from tests.unit.test_cli_next import PICKS, _account, _dirs, _ids, wire  # noqa: F401 (fixtures)

runner = CliRunner()
NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)  # Tuesday, 12:00 in Paris


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW)


def _lock(tmp_path):
    return tmp_path / "data" / "auto.lock"


def _due(tmp_path, repo, post_id="20260922-aaaa"):
    """A rendered post of @reads whose slot came ten minutes ago."""
    items = [PostItem(manhwa=m, hook="h") for m in PICKS]
    repo.save(
        post(id=post_id, account="reads", items=items, scheduled_at=NOW - timedelta(minutes=10))
    )
    covers = FakeCovers({m.anilist_id: tmp_path / f"{m.anilist_id}.jpg" for m in PICKS})
    render_post(post_id, PostTools(repo, covers, FakeRenderer(), lambda text: None))


def _phone(monkeypatch, posted=True):
    """MANHWATOK_UPLOADER=phone, with a fake phone; returns it and the settings it was built with."""
    monkeypatch.setenv("MANHWATOK_UPLOADER", "phone")
    report = UploadReport(attached=True, captioned=True, problems=[], titled=True, posted=posted)
    phone, built = FakeUploader(report), []

    def build(settings):
        built.append(settings)
        return phone

    monkeypatch.setattr(container, "build_uploader", build)
    return phone, built


def test_auto_once_fills_the_plan_and_stops(tmp_path, wire):
    repo, _ = wire
    _account(tmp_path, ["theme:isekai"], slots=["mon 19:00", "thu 19:00"])

    result = runner.invoke(app, ["auto", "--once"])

    assert result.exit_code == 0, result.output
    made = _ids(result.output)
    assert len(made) == 2 and {p.id for p in repo.list()} == set(made)
    assert "@reads" in result.output and "Thu 24 Sep 19:00" in result.output
    assert not _lock(tmp_path).exists()


def test_auto_once_again_makes_nothing_new(tmp_path, wire):
    repo, _ = wire
    _account(tmp_path, ["theme:isekai"], slots=["thu 19:00"])
    runner.invoke(app, ["auto", "--once"])
    result = runner.invoke(app, ["auto", "--once"])
    assert result.exit_code == 0 and len(repo.list()) == 1
    assert "nothing to do" in result.output


def test_auto_looks_as_many_days_ahead_as_it_is_told(tmp_path, wire):
    repo, _ = wire
    _account(tmp_path, ["theme:isekai"], slots=["mon 19:00", "thu 19:00"])
    runner.invoke(app, ["auto", "--once", "--days", "3"])
    assert len(repo.list()) == 1  # Thursday is within three days, Monday is not


def test_auto_goes_round_again_after_a_wait_until_it_is_stopped(tmp_path, wire, monkeypatch):
    repo, _ = wire
    _account(tmp_path, ["theme:isekai"], slots=["thu 19:00"])
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_sleep", sleep)

    result = runner.invoke(app, ["auto", "--every", "5"])

    assert result.exit_code == 0, result.output
    assert waits == [300, 300]
    assert "stopped" in result.output and not _lock(tmp_path).exists()


def test_a_round_that_fails_does_not_stop_the_rounds_after_it(tmp_path, wire, monkeypatch):
    from manhwatok.app import auto

    _account(tmp_path, ["theme:isekai"], slots=["thu 19:00"])
    real, rounds = auto.tick, []

    def tick(*args, **kwargs):
        rounds.append(1)
        if len(rounds) == 1:
            raise ManhwatokError("database is locked")
        return real(*args, **kwargs)

    def sleep(seconds):
        if len(rounds) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(auto, "tick", tick)
    monkeypatch.setattr(cli, "_sleep", sleep)

    result = runner.invoke(app, ["auto"])

    assert result.exit_code == 0, result.output
    assert "database is locked" in result.output and len(_ids(result.output)) == 1


def test_a_second_auto_is_refused_while_one_is_running(tmp_path, wire):
    _account(tmp_path, ["theme:isekai"], slots=["thu 19:00"])
    _lock(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    _lock(tmp_path).write_text(str(os.getpid()))  # this very process: certainly alive

    result = runner.invoke(app, ["auto", "--once"])

    assert result.exit_code == 1 and "already running" in result.output
    assert _lock(tmp_path).read_text() == str(os.getpid())  # the other one's lock is left


def test_a_lock_left_by_an_auto_that_died_is_taken_over(tmp_path, wire):
    repo, _ = wire
    _account(tmp_path, ["theme:isekai"], slots=["thu 19:00"])
    _lock(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    _lock(tmp_path).write_text("not a pid")

    result = runner.invoke(app, ["auto", "--once"])

    assert result.exit_code == 0, result.output
    assert len(repo.list()) == 1 and not _lock(tmp_path).exists()


def test_auto_with_the_browser_only_builds_and_says_so(tmp_path, wire):
    repo, _ = wire
    _account(tmp_path, ["theme:isekai"], auto_upload=True)
    _due(tmp_path, repo)

    result = runner.invoke(app, ["auto", "--once"])

    assert result.exit_code == 0, result.output
    assert "MANHWATOK_UPLOADER=phone" in result.output
    assert repo.get("20260922-aaaa").sent_at is None


def test_auto_says_nothing_about_uploading_when_no_account_asked_for_it(tmp_path, wire):
    _account(tmp_path, ["theme:isekai"], slots=["thu 19:00"])
    assert "MANHWATOK_UPLOADER" not in runner.invoke(app, ["auto", "--once"]).output


def test_auto_sends_a_due_post_through_the_accounts_phone_tapping_post_itself(
    tmp_path, wire, monkeypatch
):
    repo, _ = wire
    _account(tmp_path, ["theme:isekai"], auto_upload=True, phone="SERIAL1")
    _due(tmp_path, repo)
    phone, built = _phone(monkeypatch)

    result = runner.invoke(app, ["auto", "--once"])

    assert result.exit_code == 0, result.output
    assert [(s.uploader, s.auto_post, s.phone) for s in built] == [("phone", True, "SERIAL1")]
    assert [u[0] for u in phone.uploads] == ["reads"]
    assert repo.get("20260922-aaaa").sent_at == NOW
    assert "post 20260922-aaaa is out" in result.output
    with SqliteStore(tmp_path / "data" / "manhwatok.db") as store:
        assert store.history.recent("reads", NOW - timedelta(days=1)) == {11, 22}
