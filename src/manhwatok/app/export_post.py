"""Copy a rendered post's slides and caption somewhere convenient for uploading. The first
export of an account's post is what counts as "posted" for its repeat window."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from manhwatok.app.render_post import CAPTION_FILE, unfinished_error
from manhwatok.domain.errors import NotRendered, StorageError
from manhwatok.ports.posts import PostRepository
from manhwatok.ports.store import HistoryRepository


def export_post(
    post_id: str,
    posts: PostRepository,
    history: HistoryRepository,
    dest_root: Path,
    now: datetime,
) -> Path:
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
    if post.account and post.exported_at is None:
        # History first: record() is idempotent, so if saving the post fails the next export
        # simply records again; the other order could lose the history for good.
        history.record(post.account, post.id, [i.manhwa.anilist_id for i in post.items], now)
        posts.save(post.model_copy(update={"exported_at": now}))
    return dest
