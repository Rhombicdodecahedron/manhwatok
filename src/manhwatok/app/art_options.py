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
from manhwatok.ports.art import ArtOption, ArtSource


def list_art(
    post_id: str,
    anilist_id: int,
    tools: PostTools,
    source: ArtSource,
    tag: str | None = None,
) -> list[ArtOption]:
    """What `source` has for this title of the post, best order first. `tag` narrows it where
    the source understands such a thing."""
    post = tools.posts.get(post_id)
    return source.options(post.items[find_index(post, anilist_id)].manhwa, tag)


def use_art(
    post_id: str, anilist_id: int, option: ArtOption, tools: PostTools, source: ArtSource
) -> Path:
    """Download `option` and keep it as this title's art. Returns where it was kept."""
    post = tools.posts.get(post_id)
    find_index(post, anilist_id)  # fail before downloading, not after
    with tempfile.TemporaryDirectory(prefix="manhwatok-art-") as tmp:
        got = source.fetch(option, Path(tmp))
        return set_item_art(post_id, anilist_id, got, tools)
