"""Change a post's picks — in the editor (CLI) or from a form (TUI) — save and re-render."""

from __future__ import annotations

from pathlib import Path

from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_post
from manhwatok.domain.draft import check_picks, parse_draft, render_draft
from manhwatok.domain.errors import DraftError
from manhwatok.domain.post import PostItem


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
