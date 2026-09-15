"""Delete a post's folder. Its history rows (if it was exported) stay in the database."""

from __future__ import annotations

import shutil

from manhwatok.domain.errors import PostNotFound, StorageError
from manhwatok.ports.posts import PostRepository


def _no_post(post_id: str) -> PostNotFound:
    return PostNotFound(f"no post {post_id} — see `manhwatok posts`")


def leftover_state(post_id: str, posts: PostRepository) -> str:
    """For an id whose post can't be loaded: "empty" if its folder holds nothing (a build died
    right after reserving the id), else "unreadable". Raises PostNotFound if there's no folder."""
    folder = posts.folder(post_id)
    if not folder.is_dir():
        raise _no_post(post_id)
    try:
        empty = next(folder.iterdir(), None) is None
    except OSError:
        empty = False
    return "empty" if empty else "unreadable"


def delete_post(post_id: str, posts: PostRepository) -> None:
    folder = posts.folder(post_id)
    if not folder.is_dir():
        raise _no_post(post_id)
    try:
        shutil.rmtree(folder)
    except OSError as e:
        raise StorageError(f"could not delete post {post_id}: {e}") from e
