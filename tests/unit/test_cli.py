from typer.testing import CliRunner

from manhwatok.cli import app

runner = CliRunner()


def test_help_runs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "TikTok" in result.output
