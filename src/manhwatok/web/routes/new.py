"""New post: search as the TUI's Build does (an account's filters and history, a theme or
tags/genres), pick and order the titles in the page, then save and render."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.app.build_post import prefill_items
from manhwatok.app.suggest import suggest_for_account
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.labels import chapter_label
from manhwatok.domain.models import ArtStyle, CoverStyle, SearchQuery, Sort
from manhwatok.domain.post import DEFAULT_ACCENT, DEFAULT_HASHTAGS, MAX_ITEMS
from manhwatok.domain.text import split_names
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
