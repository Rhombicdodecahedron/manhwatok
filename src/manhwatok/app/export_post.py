"""Copy a rendered post's slides and caption somewhere convenient for uploading. Exporting an
account's post is what counts its titles as "posted" for the repeat window, dated with the
post's first export."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from manhwatok.app.render_post import rendered_files, unfinished_error
from manhwatok.domain.errors import StorageError
from manhwatok.ports.posts import PostRepository
from manhwatok.ports.store import ChapterRepository, HistoryRepository


def export_post(
    post_id: str,
    posts: PostRepository,
    history: HistoryRepository,
    dest_root: Path,
    now: datetime,
    chapters: ChapterRepository | None = None,
) -> Path:
    post = posts.get(post_id)
    if post.is_unfinished:
        raise unfinished_error(post_id)
    slides, caption = rendered_files(post, posts)
    dest = dest_root / post_id
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for old in dest.glob("[0-9][0-9].png"):
            old.unlink()
        for f in [*slides, caption]:
            shutil.copy2(f, dest / f.name)
    except OSError as e:
        raise StorageError(f"could not export post {post_id} to {dest}: {e}") from e
    if post.chapter and chapters is not None:
        # A chapter part counts as published the first time it leaves for TikTok, as a list
        # post's titles count as posted on its first export.
        chapters.mark_published(post.id, post.exported_at or now)
    if post.account:
        # Every export records the current titles (idempotent per title and post, dated with
        # the post's first export), so a title swapped in by `edit` after the first export is
        # protected too. History first: if saving the post fails, the next export simply
        # records again; the other order could lose the history for good.
        exported_at = post.exported_at or now
        history.record(
            post.account, post.id, [i.manhwa.anilist_id for i in post.items], exported_at
        )
        if post.exported_at is None:
            posts.save(post.model_copy(update={"exported_at": now}))
    return dest
