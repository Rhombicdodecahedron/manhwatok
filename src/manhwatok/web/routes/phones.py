"""Phones: which are plugged in, what each shows right now, and which accounts live on each."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from manhwatok.adapters.phones import Phone, check_serial
from manhwatok.adapters.tiktok_app import TikTokApp
from manhwatok.domain.errors import ManhwatokError
from manhwatok.web.routes.common import ctx_of, page

router = APIRouter()


@router.get("/phones", response_class=HTMLResponse)
def phones_page(request: Request) -> HTMLResponse:
    ctx = ctx_of(request)
    helper = request.app.state.phones
    package = ctx.settings.tiktok_app or TikTokApp().package
    accounts = ctx.store.accounts.list()
    try:
        found, error = helper.list(), ""
    except ManhwatokError as e:
        found, error = [], str(e)
    ready = [p for p in found if p.ready]
    cards = []
    for phone in found:
        here = [a for a in accounts if a.phone == phone.serial]
        loose = [a for a in accounts if not a.phone] if phone.ready and len(ready) == 1 else []
        cards.append({
            "phone": phone,
            "accounts": here,
            "loose": loose,
            "tiktok": helper.tiktok(phone.serial, package) if phone.ready else None,
        })
    return page(request, "phones.html", page="phones", cards=cards, error=error,
                seen=_seen(found, error))


def _seen(found: list[Phone], error: str) -> str:
    """What the page shows, in short: it reloads when this changes (a phone plugged in, out, or allowed)."""
    return error or " ".join(sorted(f"{p.serial}:{p.state}" for p in found))


@router.get("/phones/seen", response_class=PlainTextResponse)
def phones_seen(request: Request) -> str:
    try:
        return _seen(request.app.state.phones.list(), "")
    except ManhwatokError as e:
        return _seen([], str(e))


@router.get("/phones/{serial}/screen.png")
def phone_screen(request: Request, serial: str) -> Response:
    try:
        frame = request.app.state.phones.screen(check_serial(serial))
    except ManhwatokError:
        raise HTTPException(404) from None
    return Response(frame, media_type="image/png", headers={"Cache-Control": "no-store"})
