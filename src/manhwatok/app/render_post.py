"""Render a saved post's slides and caption into its folder."""

from __future__ import annotations

from pathlib import Path

from manhwatok.app.post_tools import PostTools
from manhwatok.domain.caption import build_caption
from manhwatok.domain.errors import DraftError, MetadataError, NotRendered, StorageError
from manhwatok.domain.post import ListPost
from manhwatok.ports.posts import PostRepository

CAPTION_FILE = "caption.txt"


def unfinished_error(post_id: str) -> DraftError:
    return DraftError(f"post {post_id} has no items — fix with: manhwatok edit {post_id}")


def rendered_files(post: ListPost, posts: PostRepository) -> tuple[list[Path], Path]:
    """The post's slides (01.png, 02.png, …) and caption.txt as `render` wrote them. Raises
    NotRendered unless there is one PNG per slide of the post and a caption."""
    folder = posts.folder(post.id)
    slides = sorted(folder.glob("[0-9][0-9].png"))
    caption = folder / CAPTION_FILE
    if len(slides) != post.slide_count or not caption.is_file():
        raise NotRendered(
            f"post {post.id} has no up-to-date slides — run: manhwatok render {post.id}"
        )
    return slides, caption


def _cover_paths(post: ListPost, tools: PostTools) -> dict[int, Path | None]:
    """Fetch covers; after the first download failure, use only what's already cached (no more
    download attempts). An item with no cover_url is just skipped — that's not an outage."""
    paths: dict[int, Path | None] = {}
    failed = False
    for item in post.items:
        m = item.manhwa
        if not m.cover_url:
            paths[m.anilist_id] = None
            continue
        if failed:
            paths[m.anilist_id] = tools.covers.cached(m)
            continue
        try:
            paths[m.anilist_id] = tools.covers.get(m)
        except MetadataError as e:
            failed = True
            paths[m.anilist_id] = None
            tools.progress(f"{e} — using plain backgrounds for the remaining covers")
    return paths


def render_post(post_id: str, tools: PostTools) -> list[Path]:
    post = tools.posts.get(post_id)
    if post.is_unfinished:
        raise unfinished_error(post_id)
    folder = tools.posts.folder(post_id)
    slides = tools.renderer.render(post, _cover_paths(post, tools), folder)
    try:
        (folder / CAPTION_FILE).write_text(build_caption(post) + "\n", encoding="utf-8")
    except OSError as e:
        raise StorageError(f"could not write caption for {post_id}: {e}") from e
    return slides
