"""Posts: every post with its status, filters, and (in the detail pane) its slides."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from manhwatok.app.context import AppContext
from manhwatok.app.post_view import post_status, scheduled_text, sent_text
from manhwatok.domain.account import DEFAULT_TIMEZONE
from manhwatok.domain.post import ListPost
from manhwatok.web.routes.common import ctx_of, page

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
