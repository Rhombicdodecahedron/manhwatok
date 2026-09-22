"""Assisted upload: a browser window attaches the slides, types the title and description and
picks a sound; the user clicks Post themselves, and only their "yes" in the terminal records
the post as sent (repeat history and `sent_at`)."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from manhwatok.app.post_tools import ProgressFn
from manhwatok.app.render_post import rendered_files, unfinished_error
from manhwatok.domain.caption import upload_description, upload_title
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.post import ListPost
from manhwatok.domain.text import clean_sounds
from manhwatok.ports.posts import PostRepository
from manhwatok.domain.account import Account
from manhwatok.ports.store import (
    AccountRepository,
    ChapterRepository,
    HistoryRepository,
    ThemeRepository,
)
from manhwatok.ports.uploader import Uploader

# Asks a yes/no question in the terminal; False for "no" and for no answer at all (EOF).
ConfirmFn = Callable[[str], bool]
# Asks which sound to use, of the post's theme and its account; None for no sound.
ChooseSoundFn = Callable[[list[str]], "str | None"]


def sounds_for(
    post: ListPost, account: Account, themes: ThemeRepository | None
) -> list[str]:
    """What to offer for this post: its theme's sounds, which suit what the post is about,
    then the account's. A theme removed since the post was built simply has none."""
    themed: list[str] = []
    if post.theme and themes is not None:
        try:
            themed = themes.get(post.theme).sounds
        except ManhwatokError:
            themed = []
    return clean_sounds([*themed, *account.sounds])


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
    sound: str | None = None,
    choose_sound: ChooseSoundFn | None = None,
    themes: ThemeRepository | None = None,
    chapters: ChapterRepository | None = None,
) -> bool:
    """True when the user confirmed the post went out (and it was recorded). `sound`: a TikTok
    sound search, "" for none; None asks `choose_sound` among the post's sounds."""
    post = posts.get(post_id)
    if post.is_unfinished:
        raise unfinished_error(post_id)
    if not post.account:
        raise ManhwatokError(f"post {post_id} has no account — build it with --account")
    account = accounts.get(post.account)
    slides, _ = rendered_files(post, posts)
    if sound is None:
        offer = sounds_for(post, account, themes)
        sound = choose_sound(offer) if offer and choose_sound else None
    sound = sound.strip() if sound else None
    if post.sent_at:
        when = post.sent_at.astimezone()
        progress(f"post {post_id} was already marked sent on {when:%Y-%m-%d} — uploading again")
    try:
        report = uploader.upload(
            account.handle, slides, upload_title(post), upload_description(post), sound, debug
        )
        if report.attached:
            progress(f"attached {len(slides)} slides")
        if report.titled:
            progress("typed the title")
        if report.captioned:
            progress("typed the description")
        if report.sound:
            progress(f"added the sound {report.sound}")
        for problem in report.problems:
            progress(problem)
        if report.debug_dir:
            progress(
                f"debug files: {report.debug_dir} (page.html can hold account details — "
                "check it before sharing)"
            )
        progress(f"slides and caption.txt: {posts.folder(post_id)}")
        progress("check the post in the browser and click Post yourself")
        posted = confirm(f"Posted on {account.display}?")
    finally:
        uploader.close()
    if posted:
        # History first, like export: if saving the post fails, the titles are still protected.
        history.record(account.handle, post.id, [i.manhwa.anilist_id for i in post.items], now)
        posts.save(post.model_copy(update={"sent_at": now}))
        if post.chapter and chapters is not None:
            # As on export: a chapter part counts as published once it leaves for TikTok. A
            # part exported earlier keeps that first date.
            chapters.mark_published(post.id, now)
    return posted
