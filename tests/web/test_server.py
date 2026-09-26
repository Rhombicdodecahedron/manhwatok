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


def test_ctrl_c_ends_the_event_streams_first():
    """Uvicorn waits for open requests before the app's own shutdown runs, and a tab's event
    stream never ends by itself: without this, Ctrl-C waits for the grace period and then
    prints the cancelled streams' tracebacks."""
    import threading

    from manhwatok.web.server import stop_streams_on_exit

    class Server:
        def __init__(self):
            self.exits = []

        def handle_exit(self, sig, frame):
            self.exits.append(sig)

    server, stop = Server(), threading.Event()
    stop_streams_on_exit(server, stop)
    server.handle_exit(2, None)
    assert stop.is_set() and server.exits == [2]


def test_no_other_site_can_frame_the_app(tmp_path):
    """Clickjacking: a page elsewhere framing the app and luring clicks onto Render or Upload
    — the clicks would be same-origin inside the frame, past the Origin check."""
    with client_for(make_ctx(tmp_path)) as client:
        for response in (client.get("/", follow_redirects=False), client.get("/posts/table")):
            assert response.headers["X-Frame-Options"] == "DENY"
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
