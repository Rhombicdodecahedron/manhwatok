"""Change a post's picks — in the editor (CLI) or from a form (TUI, web) — and its words and
accent (web), save and re-render."""

from __future__ import annotations

from pathlib import Path

from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_post
from manhwatok.domain.color import check_accent
from manhwatok.domain.draft import check_picks, parse_draft, render_draft
from manhwatok.domain.errors import DraftError
from manhwatok.domain.post import DEFAULT_CTA_FOLLOW, DEFAULT_CTA_TITLE, ListPost, PostItem


def update_picks(post_id: str, title: str, items: list[PostItem], tools: PostTools) -> list[Path]:
    """Save a new title and picks (any of the post's candidates), drop a saved broken draft and
    re-render. Returns the new slide paths."""
    check_picks(title, items)
    post = tools.posts.get(post_id)
    known = {m.anilist_id for m in post.candidates}
    for item in items:
        if item.manhwa.anilist_id not in known:
            raise DraftError(f"{item.manhwa.title} is not one of this post's candidates")
    tools.posts.save(post.model_copy(update={"title": title.strip(), "items": items}))
    tools.posts.clear_draft(post_id)
    return render_post(post_id, tools)


def edit_post(post_id: str, tools: PostTools) -> list[Path] | None:
    """Returns the new slide paths, or None if the user closed the editor without changes."""
    post = tools.posts.get(post_id)
    if post.chapter:
        raise DraftError(f"post {post_id} is a chapter post — it has no picks to edit")
    text = tools.posts.load_draft(post_id) or render_draft(post.title, post.items, post.candidates)
    edited = tools.editor(text)
    if edited is None or edited == text:
        return None
    try:
        title, items = parse_draft(edited, post.candidates)
    except DraftError as e:
        tools.posts.save_draft(post_id, edited)
        raise DraftError(f"{e} — your draft is saved; run `manhwatok edit {post_id}` again") from e
    return update_picks(post_id, title, items, tools)


TEXT_FIELDS = ("title", "hashtags", "emojis", "byline", "cta_title", "cta_follow", "accent")
_DEFAULT_TEXTS = {"cta_title": DEFAULT_CTA_TITLE, "cta_follow": DEFAULT_CTA_FOLLOW}


def update_post_texts(post_id: str, changes: dict[str, str], tools: PostTools) -> ListPost:
    """Save a post's words and accent — only the fields given, stripped. A blank end-slide text
    goes back to its default; a blank title is refused. Doesn't render: the caller does."""
    unknown = set(changes) - set(TEXT_FIELDS)
    if unknown:
        raise ValueError(f"not a post text: {', '.join(sorted(unknown))}")
    update: dict[str, str] = {}
    for name, value in changes.items():
        value = value.strip()
        if name == "title" and not value:
            raise DraftError("give the post a title")
        if name == "accent":
            value = check_accent(value)
        if name in _DEFAULT_TEXTS and not value:
            value = _DEFAULT_TEXTS[name]
        update[name] = value
    post = tools.posts.get(post_id).model_copy(update=update)
    tools.posts.save(post)
    return post
