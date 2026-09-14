"""Reopen a post's draft in the editor, save the result and re-render."""

from __future__ import annotations

from pathlib import Path

from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_post
from manhwatok.domain.draft import parse_draft, render_draft
from manhwatok.domain.errors import DraftError


def edit_post(post_id: str, tools: PostTools) -> list[Path] | None:
    """Returns the new slide paths, or None if the user closed the editor without changes."""
    post = tools.posts.get(post_id)
    text = tools.posts.load_draft(post_id) or render_draft(post.title, post.items, post.candidates)
    edited = tools.editor(text)
    if edited is None:
        return None
    try:
        title, items = parse_draft(edited, post.candidates)
    except DraftError as e:
        tools.posts.save_draft(post_id, edited)
        raise DraftError(f"{e} — your draft is saved; run `manhwatok edit {post_id}` again") from e
    tools.posts.save(post.model_copy(update={"title": title, "items": items}))
    tools.posts.clear_draft(post_id)
    return render_post(post_id, tools)
