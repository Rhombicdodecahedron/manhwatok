"""The plan, kept going with nobody at the keyboard: every account's empty slots filled, and —
for the accounts that asked for it — the post whose time has come sent out through the phone.

`tick` is one round of that and never sleeps or loops: `manhwatok auto` calls it every few
minutes, and a test calls it with whatever time it likes.

An upload here is never told "yes, it's posted" by a person, because there is no person. So a
post counts as sent only when the uploader says it tapped Post itself, which only the phone
does; anything short of that is a failed try, and after MAX_TRIES of them the post is left
overdue in the Queue for someone to look at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from manhwatok.app.context import AppContext
from manhwatok.app.fill_plan import DEFAULT_DAYS, fill, overdue_rows
from manhwatok.app.upload_post import sound_choice, upload_post
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.post import ListPost
from manhwatok.ports.uploader import Uploader

LATE = timedelta(hours=6)  # a post overdue by more than this is no longer sent unasked
MAX_TRIES = 2  # uploads of one post that may fail before it is left for a person

LogFn = Callable[[str], None]
# The uploader for one account's post — its phone, tapping Post itself.
UploaderFor = Callable[[Account], Uploader]


@dataclass
class TickReport:
    made: list[ListPost] = field(default_factory=list)  # new posts, each in its slot
    sent: list[str] = field(default_factory=list)  # ids of the posts that went out
    failed: list[str] = field(default_factory=list)  # ids of the posts that did not


def _quiet(_: str) -> None:
    pass


def _never(_: str) -> bool:
    return False


def tick(
    ctx: AppContext,
    now: datetime,
    days: int = DEFAULT_DAYS,
    uploader: UploaderFor | None = None,
    log: LogFn = _quiet,
) -> TickReport:
    """One round: fill, then send at most one post. Without `uploader` nothing is sent."""
    report = TickReport()
    accounts = ctx.store.accounts.list()
    for account in accounts:
        if account.slots and account.rotation:
            _fill(ctx, account, now, days, report, log)
    if uploader is not None:
        _send_one(ctx, [a for a in accounts if a.auto_upload], now, uploader, report, log)
    return report


def _fill(
    ctx: AppContext, account: Account, now: datetime, days: int, report: TickReport, log: LogFn
) -> None:
    def made(post: ListPost) -> None:
        report.made.append(post)
        log(f"{account.display}: post {post.id} for {post.scheduled_at:%a %d %b %H:%M}")

    try:
        fill(ctx, account.handle, now, days, lambda m: log(f"{account.display}: {m}"), made)
    except ManhwatokError as e:
        # One account's trouble (a title with no chapters left, a source that is down) is
        # not the others': say so and go on.
        log(f"{account.display}: {e}")


def _send_one(
    ctx: AppContext,
    accounts: list[Account],
    now: datetime,
    uploader: UploaderFor,
    report: TickReport,
    log: LogFn,
) -> None:
    """Send the oldest post that is due, of the accounts that upload unasked. One a round: a
    phone does one thing at a time, and the next round is only minutes away."""
    posts = ctx.tools.posts
    due = [
        row
        for row in overdue_rows(accounts, posts.list(), now)
        if now - row.post.scheduled_at <= LATE
        and row.post.auto_tries < MAX_TRIES
        and not row.post.is_unfinished
    ]
    if not due:
        return
    post, account = due[0].post, due[0].account
    if sound_choice(post, account, ctx.store.themes).ask:
        log(
            f"{account.display}: post {post.id} goes out without a sound — set one with: "
            f"manhwatok account set {account.display} --default-sound \"…\""
        )
    log(f"{account.display}: uploading post {post.id}")
    try:
        posted = upload_post(
            post.id,
            posts,
            ctx.store.accounts,
            ctx.store.history,
            uploader(account),
            _never,
            lambda m: log(f"{account.display}: {m}"),
            now=now,
            debug=False,
            themes=ctx.store.themes,
            chapters=ctx.store.chapters,
        )
    except ManhwatokError as e:
        log(f"{account.display}: {e}")
        posted = False
    if posted:
        report.sent.append(post.id)
        log(f"{account.display}: post {post.id} is out")
        return
    report.failed.append(post.id)
    tries = post.auto_tries + 1
    posts.save(posts.get(post.id).model_copy(update={"auto_tries": tries}))
    left = (
        " — left in the Queue for you" if tries >= MAX_TRIES else " — it is tried once more"
    )
    log(f"{account.display}: post {post.id} did not go out{left}")
