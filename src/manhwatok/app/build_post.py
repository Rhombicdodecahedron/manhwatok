"""Candidates → draft in the editor → saved, rendered post."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from manhwatok.app.delete_post import delete_post
from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_post
from manhwatok.domain.account import Account
from manhwatok.domain.color import is_hex_color
from manhwatok.domain.draft import is_empty_draft, parse_draft, render_draft
from manhwatok.domain.errors import DraftError, InvalidName, ManhwatokError
from manhwatok.domain.models import Manhwa
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


def check_accent(accent: str) -> str:
    if not is_hex_color(accent):
        raise InvalidName(f"accent must look like #43c9e4, got {accent!r}")
    return accent.lower()


def create_post(
    post_id: str,
    now: datetime,
    candidates: list[Manhwa],
    title: str,
    items: list[PostItem],
    account: Account | None,
    hashtags: str | None,
    accent: str | None,
) -> ListPost:
    """A new post (pure). Hashtags and accent: the override if given, else the account's, else
    the defaults. End-slide texts come from the account."""
    if hashtags is None:
        hashtags = account.hashtags if account else DEFAULT_HASHTAGS
    if accent is None:
        accent = account.accent if account else DEFAULT_ACCENT
    return ListPost(
        id=post_id,
        created_at=now,
        title=title,
        items=items,
        candidates=candidates,
        hashtags=hashtags,
        accent=check_accent(accent),
        account=account.handle if account else None,
        cta_title=account.cta_title if account else DEFAULT_CTA_TITLE,
        cta_follow=account.cta_follow if account else DEFAULT_CTA_FOLLOW,
    )


def build_post(
    find_candidates: Callable[[], list[Manhwa]],
    title: str,
    account: Account | None,
    hashtags: str | None,
    accent: str | None,
    tools: PostTools,
    now: datetime,
) -> tuple[ListPost, list[Path]] | None:
    """Returns (post, slide paths), or None if the user cancelled in the editor.
    `find_candidates` runs the search (e.g. `suggest_for_account`) once the inputs are valid."""
    if accent is not None:
        check_accent(accent)
    candidates = find_candidates()
    if not candidates:
        raise ManhwatokError("no matches — try fewer tags or a lower --min-tag-rank")
    items = [
        PostItem(manhwa=m, hook=first_sentence(m.description)) for m in candidates[:MAX_ITEMS]
    ]
    edited = tools.editor(render_draft(title, items, candidates))
    if edited is None or is_empty_draft(edited):
        return None

    post_id = tools.posts.new_id(now.astimezone().date())
    try:
        title, items = parse_draft(edited, candidates)
    except DraftError as e:
        draft = create_post(post_id, now, candidates, "", [], account, hashtags, accent)
        _save_new(draft, tools.posts)
        tools.posts.save_draft(post_id, edited)
        raise DraftError(f"{e} — your draft is saved; fix with: manhwatok edit {post_id}") from e
    post = create_post(post_id, now, candidates, title, items, account, hashtags, accent)
    _save_new(post, tools.posts)
    return post, render_post(post.id, tools)


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
