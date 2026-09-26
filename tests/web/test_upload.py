import json
import time

import pytest

pytest.importorskip("fastapi")

from manhwatok.adapters.phones import Phone  # noqa: E402
from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.ports.uploader import UploadReport  # noqa: E402
from manhwatok.web.phones import Phones  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import FakeUploader, post  # noqa: E402
from tests.web.helpers import client_for, wait_job  # noqa: E402

PID = "20260914-0002"
PHONE = "R5CY10GLA9E"


def _world(tmp_path, phones=None, report=None):
    uploader = FakeUploader(report)
    ctx = make_ctx(tmp_path, uploader=uploader)
    built = []
    ctx.uploader_with = lambda s: built.append((s.uploader, s.auto_post, s.phone)) or uploader
    ctx.store.accounts.add(Account(handle="reads", phone=PHONE, sounds=["Lofi", "Phonk"]))
    ctx.store.accounts.add(Account(handle="other", byline=""))
    ctx.tools.posts.save(post(id=PID, account="reads"))
    render_post(PID, ctx.tools)
    listed = [Phone(PHONE, "device", "SM F741B")] if phones is None else phones
    helper = Phones(list_fn=lambda: listed, screen_fn=lambda s: b"", app_fn=lambda s, p: True)
    return ctx, uploader, built, helper


def _default_sound(ctx, sound):
    reads = ctx.store.accounts.get("reads")
    ctx.store.accounts.update(reads.model_copy(update={"default_sound": sound}))


def _notice(response):
    return json.loads(response.headers["HX-Trigger"])["notice"]


def _answer_all(client, answers, timeout=5.0):
    """Answer each question as it comes, in order; returns the questions' texts."""
    asked, seen = [], set()
    for value in answers:
        deadline = time.monotonic() + timeout
        while not [q for q in client.app.state.jobs.pending() if q.id not in seen]:
            assert time.monotonic() < deadline, f"no question after {asked}"
            time.sleep(0.01)
        q = [q for q in client.app.state.jobs.pending() if q.id not in seen][0]
        seen.add(q.id)
        asked.append(q.text)
        assert client.app.state.jobs.answer(q.id, value)
    return asked


def test_the_dialog_preselects_the_posts_account_its_phone_and_the_mode(tmp_path):
    ctx, _, _, phones = _world(tmp_path)
    with client_for(ctx, phones=phones) as client:
        html = client.get(f"/posts/{PID}/upload").text
    assert '<option value="reads" selected>' in html and '<option value="other">' in html
    assert f'<option value="{PHONE}" selected>' in html
    assert '<option value="browser" selected>' in html
    assert f'hx-post="/posts/{PID}/upload"' in html


def test_an_upload_asks_its_questions_in_the_page_and_records_the_post(tmp_path):
    ctx, uploader, built, phones = _world(tmp_path)
    with client_for(ctx, phones=phones) as client:
        response = client.post(f"/posts/{PID}/upload", data={
            "account": "reads", "mode": "phone", "phone": PHONE, "visibility": "", "debug": ""})
        job_id = response.headers["HX-Redirect"].rsplit("/", 1)[1]
        asked = _answer_all(client, ["Phonk", "yes"])
        job = wait_job(client, job_id)
    assert asked == ["Sound for @reads", "Posted on @reads?"]
    assert built == [("phone", False, PHONE)]
    assert uploader.uploads[0][4] == "Phonk"
    assert job.outcome == f"recorded post {PID} as sent" and job.screen == PHONE
    assert ctx.tools.posts.get(PID).sent_at is not None


def test_uploading_as_another_account_moves_and_rerenders_the_post_first(tmp_path):
    ctx, uploader, _, phones = _world(tmp_path)
    with client_for(ctx, phones=phones) as client:
        response = client.post(f"/posts/{PID}/upload", data={
            "account": "other", "mode": "browser", "phone": "", "visibility": "private"})
        job_id = response.headers["HX-Redirect"].rsplit("/", 1)[1]
        _answer_all(client, ["no"])
        job = wait_job(client, job_id)
    assert ctx.tools.posts.get(PID).account == "other"
    assert job.log[0] == f"moved post {PID} to @other"
    assert any(line.startswith(f"post {PID} · ") for line in job.log)
    assert uploader.uploads[0][0] == "other" and uploader.uploads[0][7].value == "private"
    assert job.outcome == "nothing recorded"


def test_a_phone_that_isnt_ready_stops_the_upload_before_anything(tmp_path):
    ctx, uploader, built, phones = _world(tmp_path, phones=[Phone(PHONE, "unauthorized")])
    with client_for(ctx, phones=phones) as client:
        response = client.post(f"/posts/{PID}/upload", data={
            "account": "reads", "mode": "phone", "phone": PHONE})
    assert _notice(response) == {
        "text": f"the phone {PHONE} isn't ready — it needs you to allow USB debugging on the phone",
        "level": "error",
    }
    assert built == [] and uploader.uploads == []


def test_no_phone_plugged_in_is_said_for_phone_modes_only(tmp_path):
    ctx, uploader, _, phones = _world(tmp_path, phones=[])
    with client_for(ctx, phones=phones) as client:
        form = {"account": "reads", "mode": "phone-post"}
        refused = client.post(f"/posts/{PID}/upload", data=form)
        started = client.post(f"/posts/{PID}/upload", data={"account": "reads", "mode": "browser"})
        _answer_all(client, ["", "no"])
        wait_job(client, started.headers["HX-Redirect"].rsplit("/", 1)[1])
    assert _notice(refused)["text"] == "no phone plugged in — plug one in, or upload in the browser"


def test_an_auto_post_upload_is_recorded_without_asking(tmp_path):
    report = UploadReport(True, True, [], titled=True, posted=True)
    ctx, uploader, built, phones = _world(tmp_path, report=report)
    _default_sound(ctx, "Lofi")
    with client_for(ctx, phones=phones) as client:
        response = client.post(f"/posts/{PID}/upload", data={
            "account": "reads", "mode": "phone-post", "phone": PHONE})
        job = wait_job(client, response.headers["HX-Redirect"].rsplit("/", 1)[1])
    assert built == [("phone", True, PHONE)] and client.app.state.jobs.pending() == []
    assert job.outcome == f"recorded post {PID} as sent"


def test_bulk_upload_goes_through_the_ticked_posts_in_turn(tmp_path):
    ctx, uploader, _, phones = _world(tmp_path)
    _default_sound(ctx, "Lofi")
    ctx.tools.posts.save(post(id="20260915-0003", account="reads"))
    render_post("20260915-0003", ctx.tools)
    ctx.tools.posts.save(post(id="20260916-0004"))  # no account: skipped
    with client_for(ctx, phones=phones) as client:
        ticked = [PID, "20260915-0003", "20260916-0004"]
        client.post("/posts/bulk", data={"action": "upload", "ids": ticked})
        job = client.app.state.jobs.recent()[0]
        _answer_all(client, ["yes", "no"])
        job = wait_job(client, job.id)
    assert [u[0] for u in uploader.uploads] == ["reads", "reads"]
    assert "post 20260916-0004 has no account — skipped" in job.log
    assert job.outcome == "uploaded 2 posts, recorded 1 as sent"


def test_log_in_runs_on_the_accounts_phone(tmp_path):
    ctx, uploader, built, phones = _world(tmp_path)
    with client_for(ctx, phones=phones) as client:
        response = client.post("/accounts/reads/login", data={"mode": "phone", "phone": PHONE})
        job = wait_job(client, response.headers["HX-Redirect"].rsplit("/", 1)[1])
    assert uploader.logins == ["reads"] and built == [("phone", False, PHONE)]
    assert not job.failed


def test_the_upload_dialog_fills_its_panel_instead_of_replacing_it(tmp_path):
    """The detail pane swaps itself whole (hx-swap="outerHTML"), and htmx hands that to the
    buttons inside it unless they say otherwise — the dialog would take the panel's place."""
    ctx, _, _, phones = _world(tmp_path)
    with client_for(ctx, phones=phones) as client:
        html = client.get(f"/posts/{PID}").text
    button = html[html.index(f'hx-get="/posts/{PID}/upload"'):]
    assert 'hx-swap="innerHTML"' in button[: button.index(">")]
