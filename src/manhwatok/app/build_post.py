"""Candidates → draft in the editor → saved, rendered post."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from manhwatok.app.delete_post import delete_post
from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_post
from manhwatok.domain.account import Account
from manhwatok.domain.color import check_accent
from manhwatok.domain.draft import check_picks, is_empty_draft, parse_draft, render_draft
from manhwatok.domain.errors import DraftError, ManhwatokError
from manhwatok.domain.models import ArtStyle, Manhwa
from manhwatok.domain.post import (
    DEFAULT_ACCENT,
    DEFAULT_CTA_FOLLOW,
    DEFAULT_CTA_TITLE,
    DEFAULT_HASHTAGS,
    MAX_ITEMS,
    ListPost,
    PostItem,
)
from manhwatok.domain.text import first_sentence
from manhwatok.ports.posts import PostRepository


def create_post(
    post_id: str,
    now: datetime,
    candidates: list[Manhwa],
    title: str,
    items: list[PostItem],
    account: Account | None,
    hashtags: str | None,
    accent: str | None,
    art: ArtStyle | None = None,
    emojis: str | None = None,
    theme: str | None = None,
) -> ListPost:
    """A new post (pure). Hashtags, emojis, accent and art: the override if given, else the
    account's, else the defaults. End-slide texts come from the account."""
    if hashtags is None:
        hashtags = account.hashtags if account else DEFAULT_HASHTAGS
    if emojis is None:
        emojis = account.emojis if account else ""
    if accent is None:
        accent = account.accent if account else DEFAULT_ACCENT
    if art is None:
        art = account.art if account else ArtStyle.NONE
    return ListPost(
        id=post_id,
        created_at=now,
        theme=theme,
        title=title,
        items=items,
        candidates=candidates,
        hashtags=hashtags,
        emojis=emojis.strip(),
        accent=check_accent(accent),
        account=account.handle if account else None,
        cta_title=account.cta_title if account else DEFAULT_CTA_TITLE,
        cta_follow=account.cta_follow if account else DEFAULT_CTA_FOLLOW,
        art=art,
    )


def prefill_items(candidates: list[Manhwa]) -> list[PostItem]:
    """The picks a new post starts with: the first MAX_ITEMS candidates, each hooked with the
    first sentence of its description."""
    return [
        PostItem(manhwa=m, hook=first_sentence(m.description)) for m in candidates[:MAX_ITEMS]
    ]


def save_new_post(
    candidates: list[Manhwa],
    title: str,
    items: list[PostItem],
    account: Account | None,
    hashtags: str | None,
    accent: str | None,
    tools: PostTools,
    now: datetime,
    art: ArtStyle | None = None,
    emojis: str | None = None,
    theme: str | None = None,
) -> tuple[ListPost, list[Path]]:
    """Check the picks, save them as a new post and render it. Nothing is written if the
    picks or the style are invalid."""
    post = store_new_post(
        candidates, title, items, account, hashtags, accent, tools.posts, now, art, emojis, theme
    )
    return post, render_post(post.id, tools)


def store_new_post(
    candidates: list[Manhwa],
    title: str,
    items: list[PostItem],
    account: Account | None,
    hashtags: str | None,
    accent: str | None,
    posts: PostRepository,
    now: datetime,
    art: ArtStyle | None = None,
    emojis: str | None = None,
    theme: str | None = None,
) -> ListPost:
    """`save_new_post` short of rendering, for a caller with more to do first (art to fill)."""
    check_picks(title, items)
    post = create_post(
        "", now, candidates, title, items, account, hashtags, accent, art, emojis, theme
    )
    post = post.model_copy(update={"id": posts.new_id(now.astimezone().date())})
    _save_new(post, posts)
    return post


def build_post(
    find_candidates: Callable[[], list[Manhwa]],
    title: str,
    account: Account | None,
    hashtags: str | None,
    accent: str | None,
    tools: PostTools,
    now: datetime,
    art: ArtStyle | None = None,
    emojis: str | None = None,
    theme: str | None = None,
) -> tuple[ListPost, list[Path]] | None:
    """Returns (post, slide paths), or None if the user cancelled in the editor.
    `find_candidates` runs the search (e.g. `suggest_for_account`) once the inputs are valid."""
    if accent is not None:
        check_accent(accent)
    candidates = find_candidates()
    if not candidates:
        raise ManhwatokError("no matches — try fewer tags or a lower --min-tag-rank")
    items = prefill_items(candidates)
    edited = tools.editor(render_draft(title, items, candidates))
    if edited is None or is_empty_draft(edited):
        return None

    try:
        title, items = parse_draft(edited, candidates)
    except DraftError as e:
        post_id = tools.posts.new_id(now.astimezone().date())
        draft = create_post(
            post_id, now, candidates, "", [], account, hashtags, accent, art, emojis, theme
        )
        _save_new(draft, tools.posts)
        tools.posts.save_draft(post_id, edited)
        raise DraftError(f"{e} — your draft is saved; fix with: manhwatok edit {post_id}") from e
    return save_new_post(
        candidates, title, items, account, hashtags, accent, tools, now, art, emojis, theme
    )


def _save_new(post: ListPost, posts: PostRepository) -> None:
    """Save a post into the folder `new_id` just reserved. If that fails, remove the folder
    (best effort) so it doesn't linger as a leftover `posts` can't show."""
    try:
        posts.save(post)
    except BaseException:
        try:
            delete_post(post.id, posts)
        except ManhwatokError:
            pass
        raise
