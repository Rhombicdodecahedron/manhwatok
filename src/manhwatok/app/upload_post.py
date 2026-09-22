"""Assisted upload: a browser window attaches the slides, types the title and description,
picks a sound and — when the post is being scheduled — fills in TikTok's own schedule; the user
clicks Post (or Schedule) themselves, and only their "yes" in the terminal records the post as
sent (repeat history and `sent_at`, plus `tiktok_scheduled_at` for a scheduled one)."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from manhwatok.app.post_tools import ProgressFn
from manhwatok.app.render_post import rendered_files, unfinished_error
from manhwatok.domain.caption import upload_description, upload_title
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Visibility
from manhwatok.domain.plan import check_schedule, schedulable
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


def theme_sounds(post: ListPost, themes: ThemeRepository | None) -> list[str]:
    """The sounds of the theme the post was built from. A theme removed since — or a post
    built without one — simply has none."""
    if post.theme and themes is not None:
        try:
            return clean_sounds(themes.get(post.theme).sounds)
        except ManhwatokError:
            return []
    return []


def sounds_for(
    post: ListPost, account: Account, themes: ThemeRepository | None
) -> list[str]:
    """What to offer for this post: its theme's sounds, which suit what the post is about,
    then the account's default and the rest of its own."""
    return clean_sounds(
        [*theme_sounds(post, themes), account.default_sound, *account.sounds]
    )


def preset_sound(
    post: ListPost, account: Account, themes: ThemeRepository | None
) -> str | None:
    """The sound to use without asking: the account's default, or the post's theme's own when
    that theme has exactly one — there is nothing to choose between. None means ask."""
    if account.default_sound:
        return account.default_sound
    themed = theme_sounds(post, themes)
    return themed[0] if len(themed) == 1 else None


def schedule_for(post: ListPost, now: datetime) -> datetime | None:
    """The post's own planned time when TikTok would still take it (15 minutes to 10 days
    ahead), else None. What `upload` and the TUI fill TikTok's schedule in with by default: a
    post planned for later is scheduled, one planned for now (or long ago) simply goes out."""
    return post.scheduled_at if schedulable(post.scheduled_at, now) else None


def visibility_for(
    post: ListPost, account: Account, chosen: Visibility | None = None
) -> Visibility:
    """Who can see this post: what the upload was told to use, else the post's own choice,
    else its account's — the account's is Everyone unless it says otherwise, which is what
    TikTok itself opens on."""
    return chosen or post.visibility or account.visibility


def set_visibility(
    posts: PostRepository, post_id: str, visibility: Visibility | None
) -> ListPost:
    """Set who can see a post once it is up, or clear it with None — an upload then uses the
    post's account's own choice again."""
    post = posts.get(post_id).model_copy(update={"visibility": visibility})
    posts.save(post)
    return post


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
    schedule_at: datetime | None = None,
    ask_sound: bool = False,
    visibility: Visibility | None = None,
) -> bool:
    """True when the user confirmed the post went out (and it was recorded). `sound`: a TikTok
    sound search, "" for none; None uses `preset_sound`, else asks `choose_sound` among the
    post's sounds — `ask_sound` asks even when there is a preset one. `schedule_at` fills in
    TikTok's own schedule instead of posting now; a time TikTok wouldn't take is refused here,
    before any browser opens. `visibility` is who can see it, for this upload only: without one
    the post's own choice decides, and without that its account's."""
    post = posts.get(post_id)
    if post.is_unfinished:
        raise unfinished_error(post_id)
    if not post.account:
        raise ManhwatokError(f"post {post_id} has no account — build it with --account")
    account = accounts.get(post.account)
    if schedule_at is not None:
        check_schedule(schedule_at, now)
    slides, _ = rendered_files(post, posts)
    if sound is None:
        preset = None if ask_sound else preset_sound(post, account, themes)
        if preset is not None:
            sound = preset
        else:
            offer = sounds_for(post, account, themes)
            sound = choose_sound(offer) if offer and choose_sound else None
    sound = sound.strip() if sound else None
    if post.sent_at:
        when = post.sent_at.astimezone()
        progress(f"post {post_id} was already marked sent on {when:%Y-%m-%d} — uploading again")
    try:
        report = uploader.upload(
            account.handle,
            slides,
            upload_title(post),
            upload_description(post),
            sound,
            debug,
            schedule_at,
            visibility_for(post, account, visibility),
        )
        if report.attached:
            progress(f"attached {len(slides)} slides")
        if report.titled:
            progress("typed the title")
        if report.captioned:
            progress("typed the description")
        if report.sound:
            progress(f"added the sound {report.sound}")
        if report.visibility is not None and report.visibility is not Visibility.EVERYONE:
            progress(f"TikTok will show it to {report.visibility.spoken}")
        for note in report.notes:
            progress(note)
        if report.scheduled_at:
            progress(f"TikTok will post it on {report.scheduled_at.astimezone():%a %d %b %H:%M}")
        elif schedule_at is not None:
            progress("TikTok is still set to post now — nothing is scheduled")
        for problem in report.problems:
            progress(problem)
        if report.debug_dir:
            progress(
                f"debug files: {report.debug_dir} (page.html can hold account details — "
                "check it before sharing)"
            )
        progress(f"slides and caption.txt: {posts.folder(post_id)}")
        # The question follows what the browser really managed: a schedule TikTok refused
        # leaves an ordinary "post it now" page, and the user is asked about that instead.
        button = "Schedule" if report.scheduled_at else "Post"
        progress(f"check the post in the browser and click {button} yourself")
        asked = "Scheduled" if report.scheduled_at else "Posted"
        posted = confirm(f"{asked} on {account.display}?")
    finally:
        uploader.close()
    if posted:
        # History first, like export: if saving the post fails, the titles are still protected.
        history.record(account.handle, post.id, [i.manhwa.anilist_id for i in post.items], now)
        # A scheduled post has left for TikTok as surely as one posted by hand: it is `sent`
        # here, and `tiktok_scheduled_at` says when TikTok itself will publish it.
        sent: dict = {"sent_at": now}
        if report.scheduled_at:
            sent["tiktok_scheduled_at"] = report.scheduled_at
        posts.save(post.model_copy(update=sent))
        if post.chapter and chapters is not None:
            # As on export: a chapter part counts as published once it leaves for TikTok. A
            # part exported earlier keeps that first date.
            chapters.mark_published(post.id, now)
    return posted
