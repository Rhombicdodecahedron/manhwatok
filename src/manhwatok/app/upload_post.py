"""Assisted upload: a browser window attaches the slides and types the caption, the user clicks
Post themselves, and only their "yes" in the terminal records the post as sent (repeat history
and `sent_at`)."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from manhwatok.app.post_tools import ProgressFn
from manhwatok.app.render_post import rendered_files, unfinished_error
from manhwatok.domain.errors import ManhwatokError, StorageError
from manhwatok.ports.posts import PostRepository
from manhwatok.ports.store import AccountRepository, HistoryRepository
from manhwatok.ports.uploader import Uploader

# Asks a yes/no question in the terminal; False for "no" and for no answer at all (EOF).
ConfirmFn = Callable[[str], bool]


def upload_post(
    post_id: str,
    posts: PostRepository,
    accounts: AccountRepository,
    history: HistoryRepository,
    uploader: Uploader,
    confirm: ConfirmFn,
    progress: ProgressFn,
    now: datetime,
    debug: bool,
) -> bool:
    """True when the user confirmed the post went out (and it was recorded)."""
    post = posts.get(post_id)
    if post.is_unfinished:
        raise unfinished_error(post_id)
    if not post.account:
        raise ManhwatokError(f"post {post_id} has no account — build it with --account")
    account = accounts.get(post.account)
    slides, caption_file = rendered_files(post, posts)
    try:
        caption = caption_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise StorageError(f"could not read the caption of post {post_id}: {e}") from e
    if post.sent_at:
        when = post.sent_at.astimezone()
        progress(f"post {post_id} was already marked sent on {when:%Y-%m-%d} — uploading again")
    try:
        report = uploader.upload(account.handle, slides, caption, debug)
        if report.attached:
            progress(f"attached {len(slides)} slides")
        if report.captioned:
            progress("typed the caption")
        for problem in report.problems:
            progress(problem)
        if report.debug_dir:
            progress(f"debug files: {report.debug_dir}")
        progress(f"slides and caption.txt: {posts.folder(post_id)}")
        progress("check the post in the browser and click Post yourself")
        posted = confirm(f"Posted on {account.display}?")
    finally:
        uploader.close()
    if posted:
        # History first, like export: if saving the post fails, the titles are still protected.
        history.record(account.handle, post.id, [i.manhwa.anilist_id for i in post.items], now)
        posts.save(post.model_copy(update={"sent_at": now}))
    return posted
