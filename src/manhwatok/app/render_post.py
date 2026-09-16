"""Render a saved post's slides and caption into its folder."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from manhwatok.app.post_tools import PostTools
from manhwatok.domain.caption import build_caption
from manhwatok.domain.errors import DraftError, MetadataError, NotRendered, StorageError
from manhwatok.domain.models import ArtStyle, Manhwa
from manhwatok.domain.post import ListPost
from manhwatok.ports.posts import PostRepository, SlideArt

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


def _art_paths(post: ListPost, tools: PostTools) -> dict[int, SlideArt]:
    """Fetch each item's cover, plus whichever extra image the post's style uses. After the first
    download failure of a kind, use only what's already cached (no more attempts of that kind).
    A title with no cover_url/banner_url is just skipped — that's not an outage."""
    covers = _fetch_each(
        post, tools.covers.get, tools.covers.cached, lambda m: m.cover_url, "cover", tools
    )
    if post.art is ArtStyle.CHARACTER:
        characters = _fetch_each(
            post,
            tools.covers.get_character,
            tools.covers.cached_character,
            lambda m: m.character_url,
            "character",
            tools,
        )
        return {
            m_id: SlideArt(path, None, characters[m_id]) for m_id, path in covers.items()
        }
    if post.art is ArtStyle.NONE:
        return {m_id: SlideArt(path, None) for m_id, path in covers.items()}
    banners = _fetch_each(
        post,
        tools.covers.get_banner,
        tools.covers.cached_banner,
        lambda m: m.banner_url,
        "banner",
        tools,
    )
    return {m_id: SlideArt(path, banners[m_id]) for m_id, path in covers.items()}


def _fetch_each(
    post: ListPost,
    get: Callable[[Manhwa], Path],
    cached: Callable[[Manhwa], Path | None],
    url_of: Callable[[Manhwa], str],
    kind: str,
    tools: PostTools,
) -> dict[int, Path | None]:
    paths: dict[int, Path | None] = {}
    failed = False
    for item in post.items:
        m = item.manhwa
        if not url_of(m):
            paths[m.anilist_id] = None
            continue
        if failed:
            paths[m.anilist_id] = cached(m)
            continue
        try:
            paths[m.anilist_id] = get(m)
        except MetadataError as e:
            failed = True
            paths[m.anilist_id] = None
            tools.progress(f"{e} — using plain backgrounds for the remaining {kind}s")
    return paths


def restyle(post_id: str, art: ArtStyle, tools: PostTools) -> None:
    """Change a saved post's art style, so the next render draws it that way."""
    post = tools.posts.get(post_id)
    if post.art is not art:
        tools.posts.save(post.model_copy(update={"art": art}))


def render_post(post_id: str, tools: PostTools) -> list[Path]:
    post = tools.posts.get(post_id)
    if post.is_unfinished:
        raise unfinished_error(post_id)
    folder = tools.posts.folder(post_id)
    slides = tools.renderer.render(post, _art_paths(post, tools), folder)
    try:
        (folder / CAPTION_FILE).write_text(build_caption(post) + "\n", encoding="utf-8")
    except OSError as e:
        raise StorageError(f"could not write caption for {post_id}: {e}") from e
    return slides
