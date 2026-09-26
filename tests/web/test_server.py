import pytest

pytest.importorskip("fastapi")

from typer.testing import CliRunner  # noqa: E402

from manhwatok.cli import app as cli  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.web.helpers import BASE, client_for  # noqa: E402


def _with_echo(client):
    client.app.add_api_route("/echo", lambda: {"ok": True}, methods=["POST"])
    return client


def test_home_goes_to_posts(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/posts"


def test_a_post_from_the_app_itself_passes(tmp_path):
    with _with_echo(client_for(make_ctx(tmp_path))) as client:
        assert client.post("/echo").status_code == 200
        referer_only = {"Origin": "", "Referer": f"{BASE}/posts"}
        assert client.post("/echo", headers=referer_only).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "", "Referer": "https://evil.example/page"},
        {"Origin": ""},  # neither
        {"Origin": "http://127.0.0.1:9999"},  # another port on this computer
    ],
)
def test_a_post_from_anywhere_else_is_refused(tmp_path, headers):
    with _with_echo(client_for(make_ctx(tmp_path))) as client:
        assert client.post("/echo", headers=headers).status_code == 403


def test_a_request_for_another_host_is_refused(tmp_path):
    """DNS rebinding: a page on some domain that resolves to 127.0.0.1."""
    with client_for(make_ctx(tmp_path)) as client:
        response = client.get("/", headers={"Host": "evil.example:8421"})
    assert response.status_code == 403


def test_web_command_without_the_extra_says_how_to_install(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "fastapi", None)
    result = CliRunner().invoke(cli, ["web", "--no-open"])
    assert result.exit_code == 1
    assert "the web app needs the web extra — run: uv sync --extra web" in result.output


def test_web_command_runs_the_server(monkeypatch):
    import manhwatok.web.server as server

    calls = []
    monkeypatch.setattr(server, "run", lambda settings, port, open_browser: calls.append(
        (port, open_browser)))
    result = CliRunner().invoke(cli, ["web", "--port", "9000", "--no-open"])
    assert result.exit_code == 0
    assert calls == [(9000, False)]
