import sys

import pytest
from typer.testing import CliRunner

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app import container
from manhwatok.app.render_post import render_post
from manhwatok.cli import app
from manhwatok.domain.account import Account
from manhwatok.domain.errors import NotLoggedIn
from manhwatok.ports.uploader import UploadReport
from tests.unit.fakes import FakeUploader, make_tools, post

runner = CliRunner()
POST_ID = "20260914-a3f9"
INSTALL = "error: upload needs: uv sync --extra upload && uv run playwright install chromium"


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
    assert "attached 5 slides\ntyped the caption\n" in result.output
    assert "Posted on @reads? [y/N]" in result.output
    assert result.output.endswith(f"recorded post {POST_ID} as sent\n")
    assert browser.events == ["upload", "close"]
    assert browser.uploads[0][0] == "reads"
    assert browser.uploads[0][3] is False  # no --debug
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


def test_upload_problems_come_before_the_question(tmp_path, monkeypatch):
    _account_post(tmp_path)
    problem = "caption box not found — paste caption.txt yourself"
    browser = _browser(monkeypatch, report=UploadReport(True, False, [problem]))
    result = runner.invoke(app, ["upload", POST_ID, "--debug"], input="n\n")
    assert result.exit_code == 0, result.output
    assert result.output.index(problem) < result.output.index("Posted on @reads?")
    assert browser.uploads[0][3] is True


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
    assert result.output.startswith("Log in to @reads in the browser, then close the window.\n")
    assert "browser closed" in result.output
    assert browser.logins == ["reads"]
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
