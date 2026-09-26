"""Driving the web app in tests: a TestClient on a context of fakes (tests.tui.helpers)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.tui.helpers import NOW

BASE = "http://127.0.0.1:8421"


def client_for(ctx, **create_kwargs) -> TestClient:
    """A client whose requests come from the app's own page. Use it as a context manager so the
    app's startup and shutdown run: `with client_for(ctx) as client:`."""
    from manhwatok.web.server import create_app

    create_kwargs.setdefault("watch_interval", None)
    create_kwargs.setdefault("clock", lambda: NOW)
    app = create_app(ctx, **create_kwargs)
    return TestClient(app, base_url=BASE, headers={"Origin": BASE})


def wait_job(client: TestClient, job_id: str, timeout: float = 5.0):
    job = client.app.state.jobs.wait(job_id, timeout)
    assert not job.running, f"{job.heading} still running"
    return job
