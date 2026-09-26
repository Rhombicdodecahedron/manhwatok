from typer.testing import CliRunner

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.cli import app as cli
from manhwatok.domain.account import Account


def test_an_account_remembers_its_phone(tmp_path):
    with SqliteStore(tmp_path / "m.db") as store:
        store.accounts.add(Account(handle="reads", phone="R5CY10GLA9E"))
        assert store.accounts.get("reads").phone == "R5CY10GLA9E"


def test_older_accounts_load_without_one():
    assert Account(handle="reads").phone == ""


def test_the_cli_sets_shows_and_clears_it(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    assert runner.invoke(cli, ["account", "add", "reads"]).exit_code == 0
    assert runner.invoke(cli, ["account", "set", "reads", "--phone", "R5CY10GLA9E"]).exit_code == 0
    shown = runner.invoke(cli, ["account", "show", "reads"]).output
    assert "phone" in shown and "R5CY10GLA9E" in shown
    runner.invoke(cli, ["account", "set", "reads", "--phone", ""])
    assert "R5CY10GLA9E" not in runner.invoke(cli, ["account", "show", "reads"]).output
