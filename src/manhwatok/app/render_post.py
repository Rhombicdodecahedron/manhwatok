"""Render a saved post's slides and caption into its folder."""

from __future__ import annotations

from pathlib import Path

from manhwatok.app.post_tools import PostTools
from manhwatok.domain.caption import build_caption
from manhwatok.domain.errors import DraftError, MetadataError
from manhwatok.domain.post import ListPost

CAPTION_FILE = "caption.txt"


def unfinished_error(post_id: str) -> DraftError:
    return DraftError(f"post {post_id} has no items — fix with: manhwatok edit {post_id}")


def _cover_paths(post: ListPost, tools: PostTools) -> dict[int, Path | None]:
    """Fetch covers; after the first failure stop downloading so a dead CDN can't stall the run."""
    paths: dict[int, Path | None] = {}
    failed = False
    for item in post.items:
        m = item.manhwa
        paths[m.anilist_id] = None
        if failed:
            continue
        try:
            paths[m.anilist_id] = tools.covers.get(m)
        except MetadataError as e:
            failed = True
            tools.progress(f"{e} — using plain backgrounds for the remaining covers")
    return paths


def render_post(post_id: str, tools: PostTools) -> list[Path]:
    post = tools.posts.get(post_id)
    if post.is_unfinished:
        raise unfinished_error(post_id)
    folder = tools.posts.folder(post_id)
    slides = tools.renderer.render(post, _cover_paths(post, tools), folder)
    (folder / CAPTION_FILE).write_text(build_caption(post) + "\n", encoding="utf-8")
    return slides
