"""Upload a post from the web app — the same flow as `manhwatok upload` and the TUI's `u`, in
the browser lane: the questions come to the page, and a phone upload shows the phone."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.app.context import UPLOAD_MODE_LABELS
from manhwatok.app.login_account import login_account
from manhwatok.app.move_post import move_post
from manhwatok.app.render_post import render_post
from manhwatok.app.upload_post import (
    at_random,
    preset_sound,
    schedule_for,
    theme_sounds,
    upload_post,
    visibility_for,
)
from manhwatok.domain.account import normalize_handle
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Visibility
from manhwatok.domain.text import clean_sounds
from manhwatok.web.jobs import BROWSER, RENDER, Busy
from manhwatok.web.routes.common import STILL_RENDERING, ctx_of, done, page

router = APIRouter()


def _ready_phones(state):
    try:
        return [p for p in state.phones.list() if p.ready], None
    except ManhwatokError as e:
        return [], str(e)


def _phone_for(state, mode: str, wanted: str, owner: str = "") -> str:
    """The serial to upload on (checked), or "" for the browser. `state` is the app's, not
    the request's: jobs call this after their request has been answered."""
    if mode == "browser":
        return ""
    found = state.phones.list()
    ready = [p for p in found if p.ready]
    if wanted:
        match = next((p for p in found if p.serial == wanted), None)
        if match is None and owner:
            raise ManhwatokError(
                f"@{owner}'s phone {wanted} isn't plugged in — plug it in, or pick another phone"
            )
        if match is None:
            raise ManhwatokError(f"the phone {wanted} isn't plugged in")
        if not match.ready:
            raise ManhwatokError(f"the phone {wanted} isn't ready — it {match.problem}")
        return wanted
    if not ready:
        raise ManhwatokError("no phone plugged in — plug one in, or upload in the browser")
    if len(ready) > 1:
        raise ManhwatokError("several phones are plugged in — pick one")
    return ready[0].serial


def _upload_one(
    ctx, io, post_id: str, handle: str, uploader, now, debug, visibility,
    sound: str | None = None, random_sound: bool = False,
) -> bool:
    """`sound` and `random_sound` are what the dialog chose, as `upload --sound` and
    `--random-sound`; without them the account's own rules decide, asking on the page."""
    post = ctx.tools.posts.get(post_id)

    def choose_sound(sounds: list[str]) -> str | None:
        choices = [(s, s) for s in sounds] + [("No sound", "")]
        return io.choose(f"Sound for @{handle}", choices) or None

    def pick(sounds: list[str]) -> str:
        chosen = at_random(sounds)
        io.progress(f"sound, by chance: {chosen}")
        return chosen

    return upload_post(
        post_id, ctx.tools.posts, ctx.store.accounts, ctx.store.history, uploader,
        io.confirm, io.progress, now=now, debug=debug, sound=sound, choose_sound=choose_sound,
        themes=ctx.store.themes, chapters=ctx.store.chapters,
        schedule_at=schedule_for(post, now), visibility=visibility,
        random_sound=random_sound, pick=pick,
    )


RANDOM, NONE, CUSTOM, CHOSEN = "random", "none", "custom", "s:"  # the Sound choice's values


def _sound_groups(ctx, post, account) -> list[tuple[str, list[str]]]:
    """The sounds the dialog offers, as `upload` would: the post's theme's first, then the
    account's (its default first), each sound once."""
    themed = theme_sounds(post, ctx.store.themes)
    own = [s for s in clean_sounds([account.default_sound, *account.sounds]) if s not in themed]
    groups = [(f"Theme {post.theme}", themed), (f"{account.display}", own)]
    return [(label, sounds) for label, sounds in groups if sounds]


def _sound_default(ctx, post, account, offered: bool) -> str:
    """What the Sound choice starts on: the account's own habit, else the first on offer."""
    if account.random_sound and offered:
        return RANDOM
    preset = preset_sound(post, account, ctx.store.themes)
    if preset:
        return CHOSEN + preset
    first = next(iter(theme_sounds(post, ctx.store.themes) + account.sounds), None)
    return CHOSEN + first if first else NONE


def _sound_from(choice: str, custom: str) -> tuple[str | None, bool]:
    """(`sound`, `random_sound`) for upload_post from the Sound choice; ("", False) is none at
    all and (None, False) leaves it to the account's rules."""
    if choice == RANDOM:
        return None, True
    if choice == NONE:
        return "", False
    if choice == CUSTOM:
        if not custom.strip():
            raise ManhwatokError("type the sound to search for, or pick one")
        return " ".join(custom.split()), False
    if choice.startswith(CHOSEN) and choice[len(CHOSEN):].strip():
        return choice[len(CHOSEN):].strip(), False
    return None, False


@router.get("/posts/{post_id}/upload", response_class=HTMLResponse)
def upload_dialog(request: Request, post_id: str, account: str = "") -> HTMLResponse:
    """The dialog, for the post's own account — or for `account` when the "As" choice
    changed, so its phone is the one offered."""
    ctx = ctx_of(request)
    post = ctx.tools.posts.get(post_id)
    accounts = ctx.store.accounts.list()
    wanted = normalize_handle(account) if account else post.account
    account = next((a for a in accounts if a.handle == wanted), None)
    ready, error = _ready_phones(request.app.state)
    only = ready[0].serial if len(ready) == 1 else ""
    phone = account.phone if account and account.phone else only
    missing = bool(account and account.phone and account.phone not in {p.serial for p in ready})
    when = schedule_for(post, request.app.state.clock())
    groups = _sound_groups(ctx, post, account) if account else []
    return page(
        request, "_upload_dialog.html", post=post, accounts=accounts, account=account,
        sound_groups=groups,
        sound=_sound_default(ctx, post, account, bool(groups)) if account else NONE,
        modes=list(UPLOAD_MODE_LABELS.items()), mode=ctx.upload_mode, phones=ready,
        phone=phone, missing=missing, phones_error=error, when=when,
        visibilities=list(Visibility),
        shown=visibility_for(post, account) if account else None,
    )


@router.post("/posts/{post_id}/upload")
def start_upload(
    request: Request,
    post_id: str,
    account: str = Form(""),
    mode: str = Form("browser"),
    phone: str = Form(""),
    visibility: str = Form(""),
    debug: str = Form(""),
    sound: str = Form(""),
    custom_sound: str = Form(""),
) -> Response:
    ctx, state = ctx_of(request), request.app.state
    bus = state.bus
    if state.jobs.busy(RENDER) is not None:  # it may be rewriting this post's slides
        return done(request, STILL_RENDERING, "warning")
    try:
        post = ctx.tools.posts.get(post_id)
        if not (account or post.account):
            raise ManhwatokError("pick an account to upload as")
        handle = normalize_handle(account or post.account or "")
        target = ctx.store.accounts.get(handle)
        if mode not in UPLOAD_MODE_LABELS:
            raise ManhwatokError(f"no upload mode {mode!r}")
        serial = _phone_for(state, mode, phone or target.phone, owner="" if phone else handle)
        chosen = Visibility(visibility) if visibility else None
        sound_search, random_sound = _sound_from(sound, custom_sound)
        uploader = ctx.uploader_for(mode, serial)
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")

    def work(io) -> str:
        if handle != post.account:
            move_post(post_id, handle, ctx.store.accounts, ctx.tools.posts)
            io.progress(f"moved post {post_id} to @{handle}")
            slides = render_post(post_id, replace(ctx.tools, progress=io.progress))
            io.progress(f"post {post_id} · {len(slides)} slides")
        posted = _upload_one(ctx, io, post_id, handle, uploader,
                             state.clock(), bool(debug), chosen, sound_search, random_sound)
        bus.publish("changed", what="posts")
        return f"recorded post {post_id} as sent" if posted else "nothing recorded"

    try:
        job = request.app.state.jobs.start(BROWSER, f"upload post {post_id}", work)
    except Busy as e:
        return done(request, str(e), "warning")
    job.screen = serial or None
    response = done(request, f"uploading post {post_id}…")
    response.headers["HX-Redirect"] = f"/jobs/{job.id}"
    return response


def bulk_upload(request: Request, ids: list[str]) -> Response:
    """The Posts page's "Upload ticked": each post with its own account and that account's
    phone, in the current mode, one after another in one job."""
    ctx, state = ctx_of(request), request.app.state
    bus, mode = state.bus, ctx.upload_mode

    def work(io) -> str:
        uploaded = recorded = 0
        failed: list[str] = []
        for post_id in ids:
            try:
                post = ctx.tools.posts.get(post_id)
                if not post.account:
                    io.progress(f"post {post_id} has no account — skipped")
                    continue
                account = ctx.store.accounts.get(post.account)
                serial = _phone_for(state, mode, account.phone, owner=post.account)
                uploader = ctx.uploader_for(mode, serial)
                io.progress(f"— post {post_id} as @{post.account}")
                posted = _upload_one(ctx, io, post_id, post.account, uploader,
                                     state.clock(), False, None)
            except ManhwatokError as e:  # carry on with the next, as the TUI does
                io.progress(f"post {post_id} failed: {e}")
                failed.append(f"{post_id} {e}")
                continue
            uploaded += 1
            recorded += posted
            bus.publish("changed", what="posts")
        plural = "post" if uploaded == 1 else "posts"
        text = f"uploaded {uploaded} {plural}, recorded {recorded} as sent"
        return text + (f", {len(failed)} failed: " + "; ".join(failed) if failed else "")

    try:
        job = request.app.state.jobs.start(BROWSER, f"upload {len(ids)} posts", work)
    except Busy as e:
        return done(request, str(e), "warning")
    response = done(request, f"uploading {len(ids)} posts…")
    response.headers["HX-Redirect"] = f"/jobs/{job.id}"
    return response


@router.post("/accounts/{handle}/login")
def log_in(
    request: Request, handle: str, mode: str = Form("browser"), phone: str = Form("")
) -> Response:
    ctx, state = ctx_of(request), request.app.state
    try:
        account = ctx.store.accounts.get(normalize_handle(handle))
        serial = _phone_for(state, mode, phone or account.phone)
        uploader = ctx.uploader_for(mode, serial)
    except ManhwatokError as e:
        return done(request, str(e), "error")

    def work(io) -> str:
        login_account(account.handle, ctx.store.accounts, uploader, io.progress)
        return f"done — {account.display} can upload now"

    try:
        job = request.app.state.jobs.start(BROWSER, f"log in {account.display}", work)
    except Busy as e:
        return done(request, str(e), "warning")
    job.screen = serial or None
    response = done(request, f"logging in {account.display}…")
    response.headers["HX-Redirect"] = f"/jobs/{job.id}"
    return response
