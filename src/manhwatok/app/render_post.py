"""Render a saved post's slides and caption into its folder."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from manhwatok.app.post_tools import PostTools
from manhwatok.app.quad_art import SceneSearch, kept_scenes, prepare_quad
from manhwatok.domain.caption import build_caption
from manhwatok.domain.errors import DraftError, MetadataError, NotRendered, StorageError
from manhwatok.domain.models import QUAD_PICTURES, ArtStyle, CoverStyle, Manhwa
from manhwatok.domain.post import ListPost, PostItem
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
    """Fetch each item's cover, plus whichever extra image the post's style uses, plus the first
    four titles' characters for the quad cover. After the first download failure of a kind, use
    only what's already cached (no more attempts of that kind). A title with no cover_url,
    banner_url or character_url is just skipped — that's not an outage."""
    covers = _fetch_each(
        post, tools.covers.get, tools.covers.cached, lambda m: m.cover_url, "cover", tools
    )
    picked = _picked(post, tools)
    # The quad cover draws the first four titles' characters whatever the style.
    wanted = post.items if post.art is ArtStyle.CHARACTER else post.items[:QUAD_PICTURES]
    characters = _fetch_each(
        post,
        tools.covers.get_character,
        tools.covers.cached_character,
        lambda m: m.character_url,
        "character",
        tools,
        wanted,
    )
    if post.art in (ArtStyle.BACKGROUND, ArtStyle.PANEL):
        banners = _fetch_each(
            post,
            tools.covers.get_banner,
            tools.covers.cached_banner,
            lambda m: m.banner_url,
            "banner",
            tools,
        )
    else:
        # The other styles draw the cover, a portrait or picked art — never a banner.
        banners = {}
    galleries = _galleries(post, tools, picked, characters) if post.art is ArtStyle.QUAD else {}
    return {
        m_id: SlideArt(
            path,
            banners.get(m_id),
            characters.get(m_id),
            picked.get(m_id),
            galleries.get(m_id, ()),
        )
        for m_id, path in covers.items()
    }


def _galleries(
    post: ListPost,
    tools: PostTools,
    picked: dict[int, Path],
    first: dict[int, Path | None],
) -> dict[int, tuple[Path, ...]]:
    """Each title's quad pictures in grid order: its scenes, its picked art, then as many of its
    characters as still fit. `first` holds the first characters already fetched for the cover.
    Like the other downloads, the first failed character stops further attempts."""
    folder = tools.posts.folder(post.id)
    failed = False
    found: dict[int, tuple[Path, ...]] = {}
    for item in post.items:
        m = item.manhwa
        pics = kept_scenes(item, folder)[:QUAD_PICTURES]
        if m.anilist_id in picked and len(pics) < QUAD_PICTURES:
            pics.append(picked[m.anilist_id])
        for index in range(min(QUAD_PICTURES - len(pics), len(m.characters))):
            path = first.get(m.anilist_id) if index == 0 else None
            path = path or tools.covers.cached_character(m, index)
            if path is None and not failed:
                try:
                    path = tools.covers.get_character(m, index)
                except MetadataError as e:
                    failed = True
                    tools.progress(f"{e} — using the pictures already downloaded")
            if path is not None:
                pics.append(path)
        found[m.anilist_id] = tuple(pics)
    return found


def _picked(post: ListPost, tools: PostTools) -> dict[int, Path]:
    """Hand-picked art, by title. A name whose file has since gone is skipped rather than
    failing the render — the title falls back to its style's own art."""
    folder = tools.posts.folder(post.id)
    found = {}
    for item in post.items:
        if not item.custom_art:
            continue
        path = folder / item.custom_art
        if path.is_file():
            found[item.manhwa.anilist_id] = path
    return found


def _fetch_each(
    post: ListPost,
    get: Callable[[Manhwa], Path],
    cached: Callable[[Manhwa], Path | None],
    url_of: Callable[[Manhwa], str],
    kind: str,
    tools: PostTools,
    items: list[PostItem] | None = None,
) -> dict[int, Path | None]:
    """`url_of` fetched for each of `items` (default: all the post's)."""
    paths: dict[int, Path | None] = {}
    failed = False
    for item in post.items if items is None else items:
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


def set_cover(post_id: str, style: CoverStyle, tools: PostTools) -> None:
    """Change which cover version a saved post's next render makes 01.png."""
    post = tools.posts.get(post_id)
    if post.cover is not style:
        tools.posts.save(post.model_copy(update={"cover": style}))


def cover_version(post_id: str, style: CoverStyle, tools: PostTools) -> Path:
    """Where render left the post's `style` cover version (it may not exist yet)."""
    return tools.posts.folder(post_id) / f"cover-{style.value}.png"


def choose_cover(post_id: str, style: CoverStyle, tools: PostTools) -> Path:
    """Make `style` the post's cover: saved for every later render, and swapped into 01.png
    now when a render already drew it. Raises NotRendered (after saving) when none has."""
    set_cover(post_id, style, tools)
    version = cover_version(post_id, style, tools)
    if not version.is_file():
        raise NotRendered(
            f"post {post_id} has no {style.value} cover yet — run: manhwatok render {post_id}"
        )
    first = tools.posts.folder(post_id) / "01.png"
    try:
        shutil.copyfile(version, first)
    except OSError as e:
        raise StorageError(f"could not swap in the {style.value} cover for {post_id}: {e}") from e
    return first


def render_post(
    post_id: str, tools: PostTools, scenes: SceneSearch | None = None
) -> list[Path]:
    """`scenes` says where a quad post's gaps are searched (default: `tools.scenes`)."""
    post = tools.posts.get(post_id)
    if post.is_unfinished:
        raise unfinished_error(post_id)
    if post.art is ArtStyle.QUAD:
        prepare_quad(post_id, tools, scenes)
        post = tools.posts.get(post_id)
    folder = tools.posts.folder(post_id)
    slides = tools.renderer.render(post, _art_paths(post, tools), folder)
    try:
        (folder / CAPTION_FILE).write_text(build_caption(post) + "\n", encoding="utf-8")
    except OSError as e:
        raise StorageError(f"could not write caption for {post_id}: {e}") from e
    return slides
