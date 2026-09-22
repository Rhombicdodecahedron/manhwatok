"""The week ahead of an account's slots: which have a post, filling the ones that don't, and
setting one post's time by hand.

Times are compared as instants in UTC throughout: a post's `scheduled_at` comes back from
post.json with a fixed offset, and a slot inside a repeated autumn hour would never compare equal
to it in its own zone (see `domain.plan.local_time`)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, NamedTuple
from zoneinfo import ZoneInfo

from manhwatok.app.context import AppContext
from manhwatok.app.next_post import WarnFn, make_next_post
from manhwatok.domain.account import DEFAULT_TIMEZONE, Account, normalize_handle
from manhwatok.domain.errors import AccountNotFound, ManhwatokError
from manhwatok.domain.plan import is_slot, parse_when, upcoming_slots
from manhwatok.domain.post import ListPost
from manhwatok.ports.posts import PostRepository
from manhwatok.ports.store import AccountRepository

DEFAULT_DAYS = 7
MAX_FILL_DAYS = 10  # TikTok schedules a post at most 10 days ahead


class PlanRow(NamedTuple):
    """One line of the plan: a time, whose it is, and the post going out then (None for a slot
    nothing has taken yet). `at` is in the account's time zone. `on_slot` is False for a post
    scheduled at a time that isn't one of the account's slots (set by hand, or a slot since
    removed), so it isn't hidden."""

    at: datetime
    account: Account
    post: ListPost | None
    on_slot: bool


def _noop(_: str) -> None:
    pass


def _ignore(_: ListPost) -> None:
    pass


def _utc(when: datetime) -> datetime:
    return when.astimezone(timezone.utc)


def plan_rows(
    accounts: list[Account], posts: list[ListPost], now: datetime, days: int
) -> list[PlanRow]:
    """Every slot of `accounts` after `now` and up to `now + days`, each with the posts
    scheduled for it (one row per post, or one empty row), plus their posts scheduled in that
    time at no slot. In time order, then by account and post id."""
    start, end = _utc(now), _utc(now) + timedelta(days=days)
    rows: list[PlanRow] = []
    for account in accounts:
        zone = ZoneInfo(account.timezone)
        by_time: dict[datetime, list[ListPost]] = {}
        for p in posts:
            if p.account == account.handle and p.scheduled_at is not None:
                by_time.setdefault(_utc(p.scheduled_at), []).append(p)
        for slot in upcoming_slots(account, now, days):
            taken = by_time.pop(_utc(slot), [])
            rows += [PlanRow(slot, account, p, True) for p in taken] or [
                PlanRow(slot, account, None, True)
            ]
        for when, taken in by_time.items():  # what's left is at no slot
            if start < when <= end:
                rows += [PlanRow(when.astimezone(zone), account, p, False) for p in taken]
    return sorted(
        rows, key=lambda r: (_utc(r.at), r.account.handle, r.post.id if r.post else "")
    )


def overdue_rows(accounts: list[Account], posts: list[ListPost], now: datetime) -> list[PlanRow]:
    """The posts of `accounts` scheduled at `now` or before that aren't sent yet — the ones
    `plan_rows` no longer shows — oldest first, each at its time in its account's zone."""
    by_handle = {account.handle: account for account in accounts}
    rows = [
        PlanRow(
            p.scheduled_at.astimezone(ZoneInfo(account.timezone)),
            account,
            p,
            is_slot(account, p.scheduled_at),
        )
        for p in posts
        if p.scheduled_at is not None
        and p.sent_at is None
        and (account := by_handle.get(p.account or "")) is not None
        and _utc(p.scheduled_at) <= _utc(now)
    ]
    return sorted(rows, key=lambda r: (_utc(r.at), r.account.handle, r.post.id))


def fill(
    ctx: AppContext,
    handle: str,
    now: datetime,
    days: int = DEFAULT_DAYS,
    warn: WarnFn = _noop,
    on_post: Callable[[ListPost], None] = _ignore,
) -> list[ListPost]:
    """Make the account's next post (as `next` does) for each of its slots in the next `days`
    days that no post of its has yet, and schedule it there; returns them in slot order.

    Running it again makes nothing new. A sent post keeps its slot. It stops at the first
    failure and raises it: the posts made before it are saved and scheduled, and each was
    passed to `on_post` as soon as it was, so a caller can show them."""
    if not 1 <= days <= MAX_FILL_DAYS:
        raise ManhwatokError(
            f"fill 1–{MAX_FILL_DAYS} days ahead (TikTok schedules at most "
            f"{MAX_FILL_DAYS} days out), got {days}"
        )
    account = ctx.store.accounts.get(normalize_handle(handle))
    if not account.slots:
        raise ManhwatokError(
            f"{account.display} has no slots — set them with: manhwatok account set "
            f'{account.display} --slots "mon 19:00,thu 19:00"'
        )
    empty = [
        row.at
        for row in plan_rows([account], ctx.tools.posts.list(), now, days)
        if row.post is None
    ]
    made: list[ListPost] = []
    for slot in empty:
        post = make_next_post(ctx, account.handle, now, warn)
        post = post.model_copy(update={"scheduled_at": slot})
        ctx.tools.posts.save(post)
        made.append(post)
        on_post(post)
    return made


def schedule_post(
    posts: PostRepository,
    accounts: AccountRepository,
    post_id: str,
    when: str | None,
    now: datetime,
) -> ListPost:
    """Set when a post goes out, or clear it with None. `when` is `YYYY-MM-DD HH:MM` or
    `<day> HH:MM` (the next such time), read in the post's account's time zone, or in
    Europe/Paris for a post with no account (or one since removed)."""
    post = posts.get(post_id)
    if when is None:
        post = post.model_copy(update={"scheduled_at": None})
    else:
        if post.sent_at is not None:
            raise ManhwatokError(f"post {post.id} is already sent")
        zone = DEFAULT_TIMEZONE
        if post.account:
            try:
                zone = accounts.get(post.account).timezone
            except AccountNotFound:
                pass
        post = post.model_copy(update={"scheduled_at": parse_when(when, zone, now)})
    posts.save(post)
    return post
