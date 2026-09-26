"""The header: how uploads go (as the TUI's `b`), and what is running."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from manhwatok.domain.errors import ManhwatokError
from manhwatok.web.routes.common import ctx_of, page, trigger

router = APIRouter()


@router.post("/mode", response_class=HTMLResponse)
def set_mode(request: Request, mode: str = Form(...)) -> HTMLResponse:
    ctx = ctx_of(request)
    try:
        ctx.set_upload_mode(mode)
    except ManhwatokError as e:
        return trigger(page(request, "_header.html"), str(e), "error")
    text = f"uploads and logins now go through the {ctx.upload_mode_label}"
    return trigger(page(request, "_header.html"), text)


@router.get("/busy", response_class=HTMLResponse)
def busy(request: Request) -> HTMLResponse:
    return page(request, "_busy.html")
