"""Copy a rendered post's slides and caption somewhere convenient for uploading."""

from __future__ import annotations

import shutil
from pathlib import Path

from manhwatok.app.render_post import CAPTION_FILE, unfinished_error
from manhwatok.domain.errors import NotRendered, StorageError
from manhwatok.ports.posts import PostRepository


def export_post(post_id: str, posts: PostRepository, dest_root: Path) -> Path:
    post = posts.get(post_id)
    if post.is_unfinished:
        raise unfinished_error(post_id)
    folder = posts.folder(post_id)
    slides = sorted(folder.glob("[0-9][0-9].png"))
    caption = folder / CAPTION_FILE
    if len(slides) != post.slide_count or not caption.is_file():
        raise NotRendered(
            f"post {post_id} has no up-to-date slides — run: manhwatok render {post_id}"
        )
    dest = dest_root / post_id
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for old in dest.glob("[0-9][0-9].png"):
            old.unlink()
        for f in [*slides, caption]:
            shutil.copy2(f, dest / f.name)
    except OSError as e:
        raise StorageError(f"could not export post {post_id} to {dest}: {e}") from e
    return dest
