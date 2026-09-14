"""Theme → candidates → draft in the editor → saved, rendered post."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_post
from manhwatok.app.suggest import suggest_titles
from manhwatok.domain.color import is_hex_color
from manhwatok.domain.draft import parse_draft, render_draft
from manhwatok.domain.errors import DraftError, ManhwatokError
from manhwatok.domain.models import SearchQuery
from manhwatok.domain.post import ListPost, PostItem
from manhwatok.domain.text import first_sentence
from manhwatok.ports.metadata import ChapterSource, MetadataSource


def build_post(
    query: SearchQuery,
    title: str,
    hashtags: str,
    accent: str,
    metadata: MetadataSource,
    chapters: ChapterSource | None,
    tools: PostTools,
    now: datetime,
) -> tuple[ListPost, list[Path]] | None:
    """Returns (post, slide paths), or None if the user closed the editor without changes."""
    if not is_hex_color(accent):
        raise ManhwatokError(f"accent must look like #43c9e4, got {accent!r}")
    candidates = suggest_titles(query, metadata, chapters, progress=tools.progress)
    if not candidates:
        raise ManhwatokError("no matches — try fewer tags or a lower --min-tag-rank")
    items = [PostItem(manhwa=m, hook=first_sentence(m.description)) for m in candidates]
    edited = tools.editor(render_draft(title, items, candidates))
    if edited is None:
        return None

    post = ListPost(
        id=tools.posts.new_id(now.astimezone().date()),
        created_at=now,
        candidates=candidates,
        hashtags=hashtags,
        accent=accent.lower(),
    )
    try:
        title, items = parse_draft(edited, candidates)
    except DraftError as e:
        tools.posts.save(post)
        tools.posts.save_draft(post.id, edited)
        raise DraftError(f"{e} — your draft is saved; fix with: manhwatok edit {post.id}") from e
    post = post.model_copy(update={"title": title, "items": items})
    tools.posts.save(post)
    return post, render_post(post.id, tools)
