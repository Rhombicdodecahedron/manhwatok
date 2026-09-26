"""New post: search as the TUI's Build does (an account's filters and history, a theme or
tags/genres), pick and order the titles in the page, then save and render."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.app.build_post import prefill_items, store_new_post
from manhwatok.app.render_post import render_post
from manhwatok.app.suggest import suggest_for_account
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.labels import chapter_label
from manhwatok.domain.models import ArtStyle, CoverStyle, SearchQuery, Sort
from manhwatok.domain.post import DEFAULT_ACCENT, DEFAULT_HASHTAGS, MAX_ITEMS, PostItem
from manhwatok.domain.text import split_names
from manhwatok.web.jobs import RENDER, Busy
from manhwatok.web.routes.common import ctx_of, done, page, trigger

router = APIRouter()


def _number(text: str, name: str, low: int, high: int, default: int | None) -> int | None:
    text = text.strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        raise ManhwatokError(f"{name} must be a number") from None
    if not low <= value <= high:
        raise ManhwatokError(f"{name} must be {low}–{high}")
    return value


def _query(ctx, theme: str, tags: str, genres: str, sort: str, min_rank: str, limit: str):
    """The TUI Build's rules: a theme, or tags/genres — never both, never neither."""
    how_many = _number(limit, "How many", 1, 50, 12)
    rank = _number(min_rank, "Min tag rank", 0, 100, None)
    order = Sort(sort) if sort else None
    tag_list, genre_list = split_names(tags), split_names(genres)
    if theme:
        if tag_list or genre_list:
            raise ManhwatokError("use either a theme or tags/genres, not both")
        query = ctx.store.themes.get(theme).to_query(how_many)
        updates = {k: v for k, v in (("sort", order), ("min_tag_rank", rank)) if v is not None}
        return query.model_copy(update=updates)
    if not (tag_list or genre_list):
        raise ManhwatokError("pick a theme or give at least one tag or genre")
    return SearchQuery(
        tags=tag_list,
        genres=genre_list,
        sort=order or Sort.SCORE,
        limit=how_many,
        min_tag_rank=60 if rank is None else rank,
    )


def _account(ctx, handle: str) -> Account | None:
    return ctx.store.accounts.get(handle) if handle else None


@router.get("/new", response_class=HTMLResponse)
def new_page(request: Request) -> HTMLResponse:
    ctx = ctx_of(request)
    return page(
        request,
        "new.html",
        page="new",
        accounts=ctx.store.accounts.list(),
        themes=ctx.store.themes.list(),
        sorts=list(Sort),
    )


@router.post("/new/search", response_class=HTMLResponse)
def search(
    request: Request,
    account: str = Form(""),
    theme: str = Form(""),
    tags: str = Form(""),
    genres: str = Form(""),
    sort: str = Form(""),
    min_rank: str = Form(""),
    limit: str = Form(""),
    repeats: str = Form(""),
    chapters: str = Form(""),
    title: str = Form(""),
) -> Response:
    ctx = ctx_of(request)
    try:
        query = _query(ctx, theme, tags, genres, sort, min_rank, limit)
        who = _account(ctx, account)
        results = suggest_for_account(
            query,
            who,
            ctx.metadata,
            ctx.chapters if chapters else None,
            ctx.store.history,
            request.app.state.clock(),
            bool(repeats),
        )
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")
    draft = request.app.state.drafts.add(results, who.handle if who else None, theme or None)
    if not title and theme:
        title = ctx.store.themes.get(theme).title
    return page(
        request,
        "_new_results.html",
        draft=draft,
        picks=prefill_items(results),
        picked={m.anilist_id for m in results[:MAX_ITEMS]},
        label=chapter_label,
        title=title,
        account=who,
        defaults={"hashtags": DEFAULT_HASHTAGS, "accent": DEFAULT_ACCENT},
        arts=list(ArtStyle),
        covers=list(CoverStyle),
        max_items=MAX_ITEMS,
    )


@router.post("/new/save")
async def save(request: Request) -> Response:
    """Save the picks as a new post, then render it. The order of the posted `pick` fields is
    the order of the post; each pick's hook comes from its `hook-<id>` field."""
    form = await request.form()
    ctx = ctx_of(request)
    try:
        draft = request.app.state.drafts.get(str(form.get("draft", "")))
        by_id = {str(m.anilist_id): m for m in draft.candidates}
        picks = [str(p) for p in form.getlist("pick")]
        missing = [p for p in picks if p not in by_id]
        if missing:
            raise ManhwatokError(f"title {missing[0]} is not in this search — search again")
        items = [
            PostItem(manhwa=by_id[p], hook=str(form.get(f"hook-{p}", "")).strip()) for p in picks
        ]
        text = {name: str(form.get(name, "")).strip() for name in ("hashtags", "accent", "emojis")}
        art = str(form.get("art", ""))
        post = store_new_post(
            draft.candidates,
            str(form.get("title", "")).strip(),
            items,
            _account(ctx, draft.account or ""),
            text["hashtags"] or None,
            text["accent"] or None,
            ctx.tools.posts,
            request.app.state.clock(),
            art=ArtStyle(art) if art else None,
            emojis=text["emojis"] or None,
            theme=draft.theme,
            cover=CoverStyle(str(form.get("cover", "")) or CoverStyle.FAN.value),
        )
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")
    request.app.state.bus.publish("changed", what="posts")
    bus = request.app.state.bus

    def work(io) -> str:
        slides = render_post(post.id, replace(ctx.tools, progress=io.progress))
        io.progress(f"post {post.id} · {len(slides)} slides")
        bus.publish("changed", what="posts")
        return f"rendered post {post.id}"

    try:
        request.app.state.jobs.start(RENDER, f"render post {post.id}", work)
        text_, level = f"saved post {post.id} — rendering it…", "info"
    except Busy:
        running = request.app.state.jobs.busy(RENDER)
        other = running.heading if running else "the other render"
        text_ = f"saved post {post.id} — render it when {other} is done"
        level = "warning"
    response = trigger(Response(status_code=200), text_, level, changed=["posts"])
    response.headers["HX-Redirect"] = f"/posts?post={post.id}"
    return response
