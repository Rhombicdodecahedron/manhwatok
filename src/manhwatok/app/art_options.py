"""Pictures another catalogue has for one title of a post, and picking one of them.

AniList gives manhwatok a single cover per title. MangaDex usually has the whole run of volume
covers, so this is the way to swap the one AniList happened to pick for the one you want. A
chosen picture is downloaded and then handed to `set_item_art`, so it ends up exactly where a
hand-picked file would — the renderer needs to know nothing about where it came from.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from manhwatok.app.item_art import find_index, set_item_art
from manhwatok.app.post_tools import PostTools
from manhwatok.domain.models import ArtOrder
from manhwatok.ports.art import ArtOption, ArtSource


def list_art(
    post_id: str,
    anilist_id: int,
    tools: PostTools,
    source: ArtSource,
    tag: str | None = None,
    order: ArtOrder = ArtOrder.RELEVANCE,
) -> list[ArtOption]:
    """What `source` has for this title of the post. `tag` narrows it where the source
    understands such a thing, and `order` rearranges what comes back."""
    post = tools.posts.get(post_id)
    found = source.options(post.items[find_index(post, anilist_id)].manhwa, tag)
    return arrange(found, order)


SLIDE = 1080 / 1920  # what a picture's width/height is measured against for ArtOrder.PORTRAIT


def arrange(options: list[ArtOption], order: ArtOrder) -> list[ArtOption]:
    """Re-order `options`. Sorting is stable, so anything a source reports no size for keeps its
    place among its equals and falls to the end rather than being dropped."""
    if order is ArtOrder.RELEVANCE:
        return list(options)
    if order is ArtOrder.SIZE:
        return sorted(options, key=lambda o: -(o.width * o.height))
    return sorted(options, key=_off_slide_shape)


def _off_slide_shape(option: ArtOption) -> float:
    """How far from a slide's proportions this picture is; unmeasurable ones sort last."""
    if option.width <= 0 or option.height <= 0:
        return float("inf")
    return abs(option.width / option.height - SLIDE)


def use_art(
    post_id: str, anilist_id: int, option: ArtOption, tools: PostTools, source: ArtSource
) -> Path:
    """Download `option` and keep it as this title's art. Returns where it was kept."""
    post = tools.posts.get(post_id)
    find_index(post, anilist_id)  # fail before downloading, not after
    with tempfile.TemporaryDirectory(prefix="manhwatok-art-") as tmp:
        got = source.fetch(option, Path(tmp))
        return set_item_art(post_id, anilist_id, got, tools)
