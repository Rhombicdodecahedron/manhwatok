"""Art the user picked by hand for one title in a post.

AniList only has what AniList has: about half of manhwa have no banner, character pictures are
small, and neither is on offer for the long tail at all. This is the way round that — point a
title at a file you found yourself and it beats whatever the post's style would have fetched.
The file is copied into the post's own folder, so re-rendering and exporting keep working after
the original moves.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from manhwatok.app.post_tools import PostTools
from manhwatok.domain.errors import ManhwatokError, StorageError
from manhwatok.domain.post import ListPost

PICTURES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
PREFIX = "art-"


def set_item_art(post_id: str, anilist_id: int, source: Path, tools: PostTools) -> Path:
    """Copy `source` in as this title's art. Returns where it was kept."""
    post = tools.posts.get(post_id)
    index = find_index(post, anilist_id)
    if not source.is_file():
        raise ManhwatokError(f"no such file: {source}")
    suffix = source.suffix.lower()
    if suffix not in PICTURES:
        kinds = ", ".join(sorted(PICTURES))
        raise ManhwatokError(f"{source} is not a picture — use one of: {kinds}")
    try:
        if source.stat().st_size == 0:
            raise ManhwatokError(f"{source} is empty")
        folder = tools.posts.folder(post_id)
        folder.mkdir(parents=True, exist_ok=True)
        _remove_art(folder, anilist_id)
        kept = folder / f"{PREFIX}{anilist_id}{suffix}"
        shutil.copyfile(source, kept)
    except OSError as e:
        raise StorageError(f"could not use {source} for post {post_id}: {e}") from e
    tools.posts.save(_with_art(post, index, kept.name))
    return kept


def clear_item_art(post_id: str, anilist_id: int, tools: PostTools) -> None:
    """Drop this title's hand-picked art, so its style's own art comes back."""
    post = tools.posts.get(post_id)
    index = find_index(post, anilist_id)
    _remove_art(tools.posts.folder(post_id), anilist_id)
    if post.items[index].custom_art:
        tools.posts.save(_with_art(post, index, ""))


def find_index(post: ListPost, anilist_id: int) -> int:
    """Where this title sits in the post. Raises ManhwatokError when it isn't in it at all."""
    for index, item in enumerate(post.items):
        if item.manhwa.anilist_id == anilist_id:
            return index
    listed = "\n".join(f"  {i.manhwa.anilist_id} | {i.manhwa.title}" for i in post.items)
    raise ManhwatokError(f"post {post.id} has no title {anilist_id}. It has:\n{listed}")


def _with_art(post: ListPost, index: int, name: str) -> ListPost:
    items = list(post.items)
    items[index] = items[index].model_copy(update={"custom_art": name})
    return post.model_copy(update={"items": items})


def _remove_art(folder: Path, anilist_id: int) -> None:
    """Clear out any earlier pick, whatever its extension, so none is left orphaned."""
    for old in folder.glob(f"{PREFIX}{anilist_id}.*"):
        old.unlink(missing_ok=True)
