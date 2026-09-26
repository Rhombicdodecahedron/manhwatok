"""What every route needs: the context, rendering a page or fragment with the header's data,
and telling the page what happened (a notice) and what changed (so it refreshes)."""

from __future__ import annotations

import json
from typing import Iterable

from fastapi import Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.app.context import UPLOAD_MODE_LABELS, AppContext
from manhwatok.web.jobs import LANES


def ctx_of(request: Request) -> AppContext:
    return request.app.state.ctx


def page(request: Request, name: str, **context) -> HTMLResponse:
    ctx = ctx_of(request)
    jobs = request.app.state.jobs
    base = {
        "mode": ctx.upload_mode,
        "modes": list(UPLOAD_MODE_LABELS.items()),
        "busy": [job for lane in LANES if (job := jobs.busy(lane)) is not None],
    }
    return request.app.state.templates.TemplateResponse(request, name, {**base, **context})


def trigger(
    response: Response,
    text: str | None = None,
    level: str = "info",
    changed: Iterable[str] = (),
) -> Response:
    """htmx fires these on the page: `notice` shows a toast, `changed-<what>` refreshes."""
    events: dict = {f"changed-{what}": True for what in changed}
    if text is not None:
        events["notice"] = {"text": text, "level": level}
    if events:
        response.headers["HX-Trigger"] = json.dumps(events)
    return response


def done(
    request: Request, text: str, level: str = "info", changed: Iterable[str] = ()
) -> Response:
    """An empty answer for a button that only reports; other tabs hear about `changed` too.
    Nothing on the page is swapped for it — a failed search leaves the last results there."""
    changed = list(changed)
    for what in changed:
        request.app.state.bus.publish("changed", what=what)
    response = trigger(Response(status_code=200), text, level, changed)
    response.headers["HX-Reswap"] = "none"
    return response
