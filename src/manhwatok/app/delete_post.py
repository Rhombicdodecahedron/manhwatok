"""Delete a post's folder. Its history rows (if it was exported) stay in the database."""

from __future__ import annotations

import shutil

from manhwatok.domain.errors import PostNotFound, StorageError
from manhwatok.ports.posts import PostRepository


def delete_post(post_id: str, posts: PostRepository) -> None:
    folder = posts.folder(post_id)
    if not folder.is_dir():
        raise PostNotFound(f"no post {post_id} — see `manhwatok posts`")
    try:
        shutil.rmtree(folder)
    except OSError as e:
        raise StorageError(f"could not delete post {post_id}: {e}") from e
