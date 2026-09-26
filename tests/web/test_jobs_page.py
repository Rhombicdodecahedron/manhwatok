import json
import time

import pytest

pytest.importorskip("fastapi")

from manhwatok.web.jobs import BROWSER  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.web.helpers import client_for, wait_job  # noqa: E402


def _pending(client, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not client.app.state.jobs.pending():
        assert time.monotonic() < deadline
        time.sleep(0.01)
    return client.app.state.jobs.pending()[0]


def test_a_job_page_shows_its_log_and_outcome(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        def work(io):
            io.progress("attached 14 slides")
            return "recorded post x as sent"

        job = client.app.state.jobs.start(BROWSER, "upload post x", work)
        wait_job(client, job.id)
        html = client.get(f"/jobs/{job.id}").text
        log = client.get(f"/jobs/{job.id}/log").text
    assert "upload post x" in html and 'hx-get="/jobs/' in html
    assert "attached 14 slides" in log and "recorded post x as sent" in log


def test_a_phone_jobs_page_shows_the_phone(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        job = client.app.state.jobs.start(BROWSER, "upload", lambda io: "ok")
        job.screen = "R5CY10GLA9E"
        wait_job(client, job.id)
        assert 'data-live="/phones/R5CY10GLA9E/screen.png"' in client.get(f"/jobs/{job.id}").text


def test_a_question_shows_on_any_page_and_the_first_answer_wins(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        choices = [("Lofi", "lofi"), ("no sound", "")]
        job = client.app.state.jobs.start(
            BROWSER, "upload", lambda io: f"sound={io.choose('Sound for @reads', choices)}"
        )
        question = _pending(client)
        dialog = client.get("/questions").text
        assert "Sound for @reads" in dialog
        assert f'hx-post="/questions/{question.id}"' in dialog and 'value="lofi"' in dialog
        first = client.post(f"/questions/{question.id}", data={"value": "lofi"})
        second = client.post(f"/questions/{question.id}", data={"value": ""})
        assert wait_job(client, job.id).outcome == "sound=lofi"
        assert client.get("/questions").text.strip() == ""
    assert json.loads(second.headers["HX-Trigger"])["notice"]["level"] == "warning"
    assert first.status_code == 200


def test_an_unknown_job_is_gone(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        assert "gone" in client.get("/jobs/job999").text
