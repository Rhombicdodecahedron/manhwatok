"""Edit a post: its texts and look, its picks, and each title's picture. Every change goes
through the same app functions as the TUI and the CLI, then re-renders the post in the render
lane — one job per change, refused while another render runs."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.app.edit_post import TEXT_FIELDS, update_post_texts
from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_post, restyle, set_cover
from manhwatok.domain.errors import ManhwatokError, PostNotFound
from manhwatok.domain.models import ArtOrder, ArtSourceName, ArtStyle, CoverStyle
from manhwatok.domain.post import ListPost
from manhwatok.web.jobs import RENDER, Busy
from manhwatok.web.routes.common import ctx_of, done, page
from manhwatok.web.routes.posts import STILL_RENDERING

router = APIRouter()

Change = Callable[[PostTools], "str | None"]


def chapter_refusal(post: ListPost) -> str:
    return f"post {post.id} is a chapter post — it draws its own panels"


def start_change(
    request: Request, post_id: str, heading: str, change: Change | None, render: bool = True
) -> Response:
    """Run `change(tools)` and then render the post, as one job in the render lane."""
    ctx, bus = ctx_of(request), request.app.state.bus

    def work(io) -> str:
        tools = replace(ctx.tools, progress=io.progress)
        said = change(tools) if change is not None else None
        if render:
            slides = render_post(post_id, tools)
            io.progress(f"post {post_id} · {len(slides)} slides")
        bus.publish("changed", what="posts")
        return f"{said or heading} — rendered post {post_id}"

    try:
        request.app.state.jobs.start(RENDER, f"{heading} ({post_id})", work)
    except Busy as e:
        return done(request, str(e), "warning")
    return done(request, f"{_doing(heading)} post {post_id}…")


def _doing(heading: str) -> str:
    """"saved texts and look" → "saving" — the word the toast starts with while it runs."""
    verbs = {"saved": "saving", "changed": "changing", "filled": "filling", "cleared": "clearing"}
    first = heading.split()[0]
    return verbs.get(first, "updating")


def _rendering(request: Request) -> bool:
    return request.app.state.jobs.busy(RENDER) is not None


@router.get("/posts/{post_id}/edit", response_class=HTMLResponse)
def edit_page(request: Request, post_id: str) -> HTMLResponse:
    ctx = ctx_of(request)
    try:
        post = ctx.tools.posts.get(post_id)
    except PostNotFound:
        return page(request, "_post_gone.html", post_id=post_id, why="")
    return page(
        request,
        "edit.html",
        page="posts",
        post=post,
        chapter=chapter_refusal(post) if post.chapter else "",
        arts=list(ArtStyle),
        covers=list(CoverStyle),
        sources=list(ArtSourceName),
        orders=list(ArtOrder),
    )


@router.post("/posts/{post_id}/settings")
async def save_settings(request: Request, post_id: str) -> Response:
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    form = await request.form()
    ctx = ctx_of(request)
    try:
        post = ctx.tools.posts.get(post_id)
        texts = {name: str(form[name]) for name in TEXT_FIELDS if name in form}
        art = ArtStyle(str(form["art"])) if form.get("art") else post.art
        cover = CoverStyle(str(form["cover"])) if form.get("cover") else post.cover
        if post.chapter and (art is not post.art or cover is not post.cover):
            raise ManhwatokError(chapter_refusal(post))
        update_post_texts(post_id, texts, ctx.tools)
        if art is not post.art:
            restyle(post_id, art, ctx.tools)
        if cover is not post.cover:
            set_cover(post_id, cover, ctx.tools)
    except (ManhwatokError, ValueError, KeyError) as e:
        return done(request, str(e), "error")
    return start_change(request, post_id, "saved texts and look", None)
