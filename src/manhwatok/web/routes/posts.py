"""Posts: every post with its status, filters, and (in the detail pane) its slides."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.app.context import AppContext
from manhwatok.app.delete_post import delete_post
from manhwatok.app.export_post import export_post
from manhwatok.app.post_view import caption_text, post_status, scheduled_text, sent_text
from manhwatok.app.render_post import choose_cover, cover_version, render_post, rendered_files
from manhwatok.app.upload_post import set_visibility, sounds_for, visibility_for
from manhwatok.domain.account import DEFAULT_TIMEZONE, Account
from manhwatok.domain.caption import upload_description, upload_title
from manhwatok.domain.errors import AccountNotFound, ManhwatokError, NotRendered, PostNotFound
from manhwatok.domain.models import CoverStyle, Visibility
from manhwatok.domain.post import ListPost
from manhwatok.web.jobs import RENDER, Busy
from manhwatok.web.routes.common import ctx_of, done, page
from manhwatok.web.routes.files import file_url
from manhwatok.web.routes.upload import bulk_upload

router = APIRouter()

STATUSES = ("draft", "not rendered", "rendered", "exported", "sent")
NO_ACCOUNT = "none"  # the account filter's value for posts built without one


@dataclass
class _Row:
    post: ListPost
    status: str
    planned: str  # in the post's account's time zone
    sent: str
    thumb: str | None = None  # the rendered cover (01.png), for the card


def _url_or_none(path: Path) -> str | None:
    """The picture's URL, or None when it isn't there — a render removes each slide before
    drawing it again, and a refresh can land in between."""
    try:
        return file_url(path)
    except OSError:
        return None


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
        thumb = None
        if state not in ("draft", "not rendered"):
            thumb = _url_or_none(ctx.tools.posts.folder(post.id) / "01.png")
        rows.append(_Row(post, state, scheduled_text(post, zone), sent_text(post, zone), thumb))
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
def posts_table(
    request: Request,
    account: str = "",
    status: str = "",
    selected: str = "",
    ids: list[str] = Query(default=[]),
) -> HTMLResponse:
    """The table alone; `ids` (the ticked posts) and `selected` survive the refresh that every
    change of the posts brings — a render step, a save elsewhere."""
    rows = _rows(ctx_of(request), account, status)
    return page(request, "_posts_table.html", rows=rows, selected=selected, ticked=set(ids))




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
    accent: str  # the account's, else the post's own


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
        slides = [url for p in rendered_files(post, posts)[0] if (url := _url_or_none(p))]
    except NotRendered:
        slides = []
    covers = []
    for style in CoverStyle:
        path: Path = cover_version(post.id, style, ctx.tools)
        covers.append(_Cover(style.value, _url_or_none(path), style is post.cover))
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
        accent=account.accent if account else post.accent,
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


STILL_RENDERING = "still rendering — try again when it's done"


def _plural(n: int, word: str = "post") -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _start_render(request: Request, ids: list[str], heading: str, started: str) -> Response:
    """Render `ids` in turn in the render lane; each finished post refreshes the pages."""
    ctx, bus = ctx_of(request), request.app.state.bus

    def work(io) -> str:
        tools = replace(ctx.tools, progress=io.progress)
        def one(post_id: str) -> None:
            slides = render_post(post_id, tools)
            io.progress(f"post {post_id} · {len(slides)} slides")
            bus.publish("changed", what="posts")

        if len(ids) == 1:
            one(ids[0])  # its error is the job's
            return f"rendered post {ids[0]}"
        done_count, failed = _each(ids, one, io.progress)
        return _summary("rendered", done_count, failed)

    try:
        request.app.state.jobs.start(RENDER, heading, work)
    except Busy as e:
        return done(request, str(e), "warning")
    return done(request, started)


def _each(ids: list[str], act, say=None) -> tuple[int, list[str]]:
    """`act` on each post in turn, carrying on past one that fails, as the TUI's bulk
    actions do; (how many went through, "<id> <why>" for each that didn't)."""
    count, failed = 0, []
    for post_id in ids:
        try:
            act(post_id)
        except ManhwatokError as e:
            failed.append(f"{post_id} {e}")
            if say is not None:
                say(f"post {post_id} failed: {e}")
            continue
        count += 1
    return count, failed


def _summary(verb: str, count: int, failed: list[str], where: str = "") -> str:
    text = f"{verb} {_plural(count)}{where}"
    return text + (f", {len(failed)} failed: " + "; ".join(failed) if failed else "")


def _rendering(request: Request) -> bool:
    return request.app.state.jobs.busy(RENDER) is not None


@router.post("/posts/bulk")
def bulk(request: Request, action: str = Form(...), ids: list[str] = Form(default=[])) -> Response:
    if not ids:
        return done(request, "tick some posts first", "warning")
    if action == "upload":
        return bulk_upload(request, ids)
    if action == "render":
        return _start_render(request, ids, f"render {_plural(len(ids))}",
                             f"rendering {_plural(len(ids))}…")
    if action not in ("export", "delete"):
        return done(request, f"no bulk action {action!r}", "error")
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    ctx = ctx_of(request)
    if action == "export":
        count, failed = _each(ids, lambda post_id: _export(request, post_id))
        text = _summary("exported", count, failed, f" → {ctx.settings.export_dir}")
    else:
        count, failed = _each(
            ids, lambda post_id: delete_post(post_id, ctx.tools.posts, ctx.store.chapters)
        )
        text = _summary("deleted", count, failed)
    return done(request, text, "warning" if failed else "info", changed=["posts"])


@router.post("/posts/{post_id}/render")
def render(request: Request, post_id: str) -> Response:
    return _start_render(request, [post_id], f"render post {post_id}",
                         f"rendering post {post_id}…")


@router.post("/posts/{post_id}/cover")
def cover(request: Request, post_id: str, style: str = Form(...)) -> Response:
    if _rendering(request):  # the renderer is writing 01.png from the post it read
        return done(request, STILL_RENDERING, "warning")
    ctx = ctx_of(request)
    try:
        chosen = CoverStyle(style)
        choose_cover(post_id, chosen, ctx.tools)
    except NotRendered:
        return _start_render(request, [post_id], f"render post {post_id}",
                             f"rendering post {post_id} with the {style} cover…")
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")
    return done(request, f"post {post_id} · {chosen.value} cover", changed=["posts"])


@router.post("/posts/{post_id}/visibility")
def visibility(request: Request, post_id: str, visibility: str = Form("")) -> Response:
    if _rendering(request):  # a quad render saves the post it read at the start again
        return done(request, STILL_RENDERING, "warning")
    ctx = ctx_of(request)
    try:
        who = Visibility(visibility) if visibility else None
        set_visibility(ctx.tools.posts, post_id, who)
        detail = _detail(ctx, post_id)
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")
    return done(request, f"post {post_id} · visible to {detail.visibility}", changed=["posts"])


def _export(request: Request, post_id: str) -> Path:
    ctx = ctx_of(request)
    return export_post(
        post_id,
        ctx.tools.posts,
        ctx.store.history,
        ctx.settings.export_dir,
        now=request.app.state.clock(),
        chapters=ctx.store.chapters,
    )


@router.post("/posts/{post_id}/export")
def export(request: Request, post_id: str) -> Response:
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    try:
        dest = _export(request, post_id)
    except ManhwatokError as e:
        return done(request, str(e), "error")
    return done(request, f"exported → {dest}", changed=["posts"])


@router.post("/posts/{post_id}/delete")
def delete(request: Request, post_id: str) -> Response:
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    ctx = ctx_of(request)
    try:
        delete_post(post_id, ctx.tools.posts, ctx.store.chapters)
    except ManhwatokError as e:
        return done(request, str(e), "error")
    return done(request, f"deleted post {post_id}", changed=["posts"])
