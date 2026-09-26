import json
import threading

import pytest

pytest.importorskip("fastapi")

from manhwatok.web.jobs import RENDER  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402


def _notice(response) -> dict:
    return json.loads(response.headers["HX-Trigger"])["notice"]


def test_the_mode_switch_changes_how_uploads_go(tmp_path):
    ctx = make_ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post("/mode", data={"mode": "phone-post"})
    assert response.status_code == 200
    assert ctx.upload_mode == "phone-post"
    assert 'value="phone-post" selected' in response.text
    assert _notice(response) == {
        "text": "uploads and logins now go through the phone, posting and sharing to the Story",
        "level": "info",
    }


def test_an_unknown_mode_changes_nothing(tmp_path):
    ctx = make_ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post("/mode", data={"mode": "fax"})
    assert ctx.upload_mode == "browser"
    assert _notice(response)["level"] == "error"


def test_busy_shows_what_runs(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        assert "idle" in client.get("/busy").text
        release = threading.Event()
        job = client.app.state.jobs.start(
            RENDER, "render post x", lambda io: release.wait(5) and "ok"
        )
        assert "render post x" in client.get("/busy").text
        release.set()
        client.app.state.jobs.wait(job.id, 5)


def test_static_files_are_served(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        for name in ("htmx.min.js", "app.js", "app.css"):
            assert client.get(f"/static/{name}").status_code == 200
