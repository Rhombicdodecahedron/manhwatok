"""Posts: every post with its status, filters, and (in the detail pane) its slides."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from manhwatok.app.context import AppContext
from manhwatok.app.post_view import caption_text, post_status, scheduled_text, sent_text
from manhwatok.app.render_post import cover_version, rendered_files
from manhwatok.app.upload_post import sounds_for, visibility_for
from manhwatok.domain.account import DEFAULT_TIMEZONE, Account
from manhwatok.domain.caption import upload_description, upload_title
from manhwatok.domain.errors import AccountNotFound, ManhwatokError, NotRendered, PostNotFound
from manhwatok.domain.models import CoverStyle, Visibility
from manhwatok.domain.post import ListPost
from manhwatok.web.routes.common import ctx_of, page
from manhwatok.web.routes.files import file_url

router = APIRouter()

STATUSES = ("draft", "not rendered", "rendered", "exported", "sent")
NO_ACCOUNT = "none"  # the account filter's value for posts built without one


@dataclass
class _Row:
    post: ListPost
    status: str
    planned: str  # in the post's account's time zone
    sent: str


def _rows(ctx: AppContext, account: str, status: str) -> list[_Row]:
    zones = {a.handle: a.timezone for a in ctx.store.accounts.list()}
    wanted = account.strip().lstrip("@")
    rows = []
    for post in sorted(ctx.tools.posts.list(), key=lambda p: p.created_at, reverse=True):
        if wanted and (post.account or NO_ACCOUNT) != wanted:
            continue
        state = post_status(post, ctx.tools.posts)
        if status and state != status:
            continue
        zone = zones.get(post.account or "", DEFAULT_TIMEZONE)
        rows.append(_Row(post, state, scheduled_text(post, zone), sent_text(post, zone)))
    return rows


@router.get("/posts", response_class=HTMLResponse)
def posts_page(
    request: Request, account: str = "", status: str = "", post: str = ""
) -> HTMLResponse:
    ctx = ctx_of(request)
    return page(
        request,
        "posts.html",
        page="posts",
        rows=_rows(ctx, account, status),
        accounts=ctx.store.accounts.list(),
        statuses=STATUSES,
        no_account=NO_ACCOUNT,
        account=account,
        status=status,
        selected=post,
    )


@router.get("/posts/table", response_class=HTMLResponse)
def posts_table(request: Request, account: str = "", status: str = "") -> HTMLResponse:
    return page(
        request, "_posts_table.html", rows=_rows(ctx_of(request), account, status), selected=""
    )



from manhwatok.web.routes.files import file_url


@dataclass
class _Cover:
    style: str
    url: str | None  # None until a render draws it
    chosen: bool


@dataclass
class _Detail:
    post: ListPost
    status: str
    account: Account | None
    account_label: str
    slides: list[str]
    covers: list[_Cover]
    caption: str
    rendered: bool
    title: str
    description: str
    sounds: list[str]
    visibility: str
    planned: str
    sent: str


def _account(ctx: AppContext, post: ListPost) -> tuple[Account | None, str]:
    if not post.account:
        return None, "no account"
    try:
        return ctx.store.accounts.get(post.account), f"@{post.account}"
    except AccountNotFound:
        return None, f"@{post.account} (removed)"


def _detail(ctx: AppContext, post_id: str) -> _Detail:
    posts = ctx.tools.posts
    post = posts.get(post_id)
    account, label = _account(ctx, post)
    try:
        slides = [file_url(p) for p in rendered_files(post, posts)[0]]
    except NotRendered:
        slides = []
    covers = []
    for style in CoverStyle:
        path: Path = cover_version(post.id, style, ctx.tools)
        covers.append(_Cover(style.value, file_url(path) if path.is_file() else None,
                             style is post.cover))
    caption, rendered = caption_text(post, posts)
    if account is not None:
        shown = visibility_for(post, account)
        sounds = sounds_for(post, account, ctx.store.themes)
    else:
        shown, sounds = post.visibility or Visibility.EVERYONE, []
    visibility = shown.spoken + ("" if post.visibility else " (the account's)")
    zone = account.timezone if account else DEFAULT_TIMEZONE
    unfinished = post.is_unfinished
    return _Detail(
        post=post,
        status=post_status(post, posts),
        account=account,
        account_label=label,
        slides=slides,
        covers=covers,
        caption=caption,
        rendered=rendered,
        title="" if unfinished else upload_title(post),
        description="" if unfinished else upload_description(post),
        sounds=sounds,
        visibility=visibility,
        planned=scheduled_text(post, zone),
        sent=sent_text(post, zone),
    )


@router.get("/posts/{post_id}", response_class=HTMLResponse)
def post_detail(request: Request, post_id: str) -> HTMLResponse:
    try:
        detail = _detail(ctx_of(request), post_id)
    except PostNotFound:
        return page(request, "_post_gone.html", post_id=post_id, why="")
    except ManhwatokError as e:  # e.g. an unreadable post.json
        return page(request, "_post_gone.html", post_id=post_id, why=str(e))
    return page(request, "_post_detail.html", d=detail, visibilities=list(Visibility))
