"""Plan: the week's calendar of slots and posts — one row per account, one column per day —
with filling an empty slot, moving a post to another and unscheduling it, over the same
`fill_plan` rows the TUI's Queue tab shows. Times are shown in each account's own zone; the
day columns are the days of this computer, which is where the calendar is read."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.app.context import AppContext
from manhwatok.app.fill_plan import (
    PlanRow,
    fill,
    fill_slot,
    overdue_rows,
    plan_rows,
    schedule_post,
)
from manhwatok.app.post_view import post_status
from manhwatok.domain.account import DEFAULT_TIMEZONE, Account, normalize_handle
from manhwatok.domain.errors import AccountNotFound, ManhwatokError, PostNotFound
from manhwatok.domain.post import ListPost
from manhwatok.domain.text import plain_title
from manhwatok.web.jobs import RENDER, Busy
from manhwatok.web.routes.common import STILL_RENDERING, ctx_of, done, page, trigger
from manhwatok.web.routes.files import file_url

router = APIRouter()

DAYS = 7  # the columns shown, and how far one fill reaches

@dataclass
class Slot:
    """One entry of a cell: a slot (with its post, or empty) and everything the page shows
    about it. `at` is in the slot's own account's time zone."""

    at: datetime
    account: Account
    post: ListPost | None
    status: str  # post_status(post) — "" for an empty slot
    on_slot: bool  # False: scheduled at a time that is no longer one of the account's slots
    past: bool  # its time has gone: an empty one can't be filled any more
    overdue: bool
    thumb: str | None  # the rendered cover (01.png), or None while there isn't one


@dataclass
class Line:
    """One account's row: its cells, one list per day of the window."""

    account: Account
    cells: list[list[Slot]]


def _window(now: datetime, week: int) -> tuple[datetime, list[date]]:
    """The 7 days the calendar shows: midnight of the week's first day in this computer's
    time zone, then each of its days. `week` counts whole weeks from this one."""
    local = now.astimezone()
    first = local.date() + timedelta(days=7 * week)
    start = datetime.combine(first, time.min, tzinfo=local.tzinfo)
    return start, [first + timedelta(days=i) for i in range(DAYS)]


def _column(at: datetime, days: list[date], ref: ZoneInfo) -> int:
    """Which day column a time falls in, read in `ref`. The window's last instant (exactly
    `start + 7 days`) lands just past the last column and is kept on it."""
    index = (at.astimezone(ref).date() - days[0]).days
    return min(max(index, 0), len(days) - 1)


def _thumb(path) -> str | None:
    """The picture's URL, or None when it isn't there — a render removes each slide before
    drawing it again, and a refresh can land in between."""
    try:
        return file_url(path)
    except OSError:
        return None


def _slot(ctx: AppContext, row: PlanRow, now: datetime, overdue: bool = False) -> Slot:
    post = row.post
    status = post_status(post, ctx.tools.posts) if post is not None else ""
    past = row.at <= now
    late = post is not None and past and post.sent_at is None
    thumb = None
    if post is not None and status not in ("draft", "not rendered"):
        thumb = _thumb(ctx.tools.posts.folder(post.id) / "01.png")
    return Slot(
        at=row.at,
        account=row.account,
        post=post,
        status=status,
        on_slot=row.on_slot,
        past=past,
        overdue=overdue or late,
        thumb=thumb,
    )


def _hint(accounts: list[Account]) -> str:
    """Why the calendar is empty, when that's sayable."""
    if not accounts:
        return "No account yet — add one with: manhwatok account add @handle"
    if not any(a.slots for a in accounts):
        who = accounts[0].display
        return (
            "No account has slots yet — set them with: manhwatok account set "
            f'{who} --slots "mon 19:00"'
        )
    return ""


def _view(request: Request, week: int, account: str) -> dict:
    """Everything the grid fragment shows: the accounts' rows, this week's overdue posts, and
    the day columns they are drawn under."""
    ctx = ctx_of(request)
    now = request.app.state.clock()
    start, days = _window(now, week)
    wanted = account.strip().lstrip("@")
    found = ctx.store.accounts.list()
    accounts = [a for a in found if a.handle == wanted] if wanted else found
    posts = ctx.tools.posts.list()
    ref = start.tzinfo
    lines = []
    for who in accounts:
        cells: list[list[Slot]] = [[] for _ in days]
        for row in plan_rows([who], posts, start, DAYS):
            cells[_column(row.at, days, ref)].append(_slot(ctx, row, now))
        lines.append(Line(who, cells))
    late = [_slot(ctx, row, now, overdue=True) for row in overdue_rows(accounts, posts, now)]
    return dict(
        lines=lines,
        overdue=late,
        days=days,
        today=now.astimezone().date(),
        week=week,
        account=wanted,
        accounts=found,
        now=now,
        hint=_hint(accounts),
    )


@router.get("/plan", response_class=HTMLResponse)
def plan_page(request: Request, week: int = 0, account: str = "") -> HTMLResponse:
    """The calendar, drawn straight away — the fragment below only refreshes it."""
    return page(request, "plan.html", page="plan", **_view(request, week, account))


@router.get("/plan/grid", response_class=HTMLResponse)
def plan_grid(request: Request, week: int = 0, account: str = "") -> HTMLResponse:
    """The calendar alone; every change of posts or accounts (or of the clock, from another
    tab) re-fetches it."""
    return page(request, "_plan_grid.html", **_view(request, week, account))


# --- filling ---------------------------------------------------------------------------------

FILLING = "filling"  # the word the toast starts with while a fill job runs


def _fill_line(post: ListPost) -> str:
    return f"{post.scheduled_at:%a %d %b %H:%M} · {plain_title(post.title) or '(untitled)'}"


@router.post("/plan/fill")
def fill_one(request: Request, account: str = Form(...), when: str = Form(...)) -> Response:
    """Make one post for one empty slot, in the render lane."""
    ctx, state = ctx_of(request), request.app.state
    try:
        handle = normalize_handle(account)
        at = datetime.fromisoformat(when)
        ctx.store.accounts.get(handle)
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")
    bus = state.bus

    def work(io) -> str:
        made = fill_slot(
            ctx, handle, at, state.clock(), io.progress,
            lambda post: bus.publish("changed", what="posts"),
        )
        return f"made post {made.id} · {_fill_line(made)}"

    try:
        state.jobs.start(RENDER, f"fill @{handle} at {at:%a %d %b %H:%M}", work)
    except Busy as e:
        return done(request, str(e), "warning")
    return done(request, f"{FILLING} @{handle} at {at:%a %d %b %H:%M}…")


@router.post("/plan/fill-all")
def fill_all(
    request: Request, week: int = Form(0), account: str = Form(""), days: int = Form(DAYS)
) -> Response:
    """Make a post for every empty slot of the accounts' next `days` — all of them, or just
    `account` — each account carrying on when another fails."""
    ctx, state = ctx_of(request), request.app.state
    wanted = normalize_handle(account) if account.strip() else ""
    found = ctx.store.accounts.list()
    if wanted and not any(a.handle == wanted for a in found):
        return done(request, f"no account @{wanted}", "error")
    handles = [a.handle for a in found if a.slots and (not wanted or a.handle == wanted)]
    if not handles:
        text = _hint([a for a in found if not wanted or a.handle == wanted])
        return done(request, text or "every slot already has a post", "warning")
    after = _window(state.clock(), week)[0]  # the first day of the week being shown
    bus = state.bus

    def work(io) -> str:
        made, failed = 0, []
        for handle in handles:
            try:
                posts = fill(
                    ctx, handle, state.clock(), days, io.progress,
                    lambda post: bus.publish("changed", what="posts"), after=after,
                )
            except ManhwatokError as e:
                io.progress(f"@{handle}: {e}")
                failed.append(f"@{handle} {e}")
                continue
            made += len(posts)
            for post in posts:
                io.progress(f"@{handle}: {_fill_line(post)}")
        verb = f"made {made} post" + ("" if made == 1 else "s")
        return verb + (f", {len(failed)} failed: " + "; ".join(failed) if failed else "")

    who = f"@{wanted}" if wanted else f"{len(handles)} accounts"
    try:
        state.jobs.start(RENDER, f"fill the next {days} days of {who}", work)
    except Busy as e:
        return done(request, str(e), "warning")
    return done(request, f"{FILLING} the empty slots of {who}…")


# --- moving and unscheduling -----------------------------------------------------------------


def _empty_slots(
    account: Account, posts: list[ListPost], start: datetime, now: datetime
) -> list[datetime]:
    """The account's empty slots in the shown week whose time is still ahead — the ones a post
    can be moved to (a time that has gone can't be scheduled)."""
    return [
        row.at
        for row in plan_rows([account], posts, start, DAYS)
        if row.post is None and row.at > now
    ]


@router.get("/plan/move/close", response_class=HTMLResponse)
def close_move(request: Request) -> HTMLResponse:
    """The menu's Close button: put nothing back."""
    return _menu(request, post=None)


def _menu(
    request: Request,
    *,
    post: ListPost | None,
    why: str = "",
    week: int = 0,
    account: str = "",
    account_label: str = "",
    slots: list[datetime] | None = None,
) -> HTMLResponse:
    return page(
        request,
        "_plan_move.html",
        post=post,
        why=why,
        week=week,
        account=account,
        account_label=account_label,
        slots=slots or [],
    )


@router.get("/plan/move/{post_id}", response_class=HTMLResponse)
def move_menu(request: Request, post_id: str, week: int = 0, account: str = "") -> HTMLResponse:
    """The move menu: the post's own account's empty slots of the shown week."""
    ctx = ctx_of(request)
    now = request.app.state.clock()
    start, _ = _window(now, week)
    post, why, label, slots = None, f"Post {post_id} is gone.", "", []
    try:
        found = ctx.tools.posts.get(post_id)
        if found.sent_at is not None:
            why = f"Post {found.id} is already sent."
        elif not found.account:
            why = "This post has no account — give it one in Posts first."
        else:
            who = ctx.store.accounts.get(found.account)
            post, why = found, ""
            label = who.display
            slots = _empty_slots(who, ctx.tools.posts.list(), start, now)
    except (PostNotFound, AccountNotFound):
        pass
    except ManhwatokError as e:
        why = str(e) or f"Post {post_id} is gone."
    return _menu(
        request, post=post, why=why, week=week, account=account, account_label=label, slots=slots
    )


def _moved(request: Request, text: str) -> Response:
    """The answer to a move: the menu closes (an empty fragment swaps into it), the notice says
    what happened, and every tab hears that the posts changed."""
    request.app.state.bus.publish("changed", what="posts")
    return trigger(_menu(request, post=None), text, "info", changed=["posts"])


def _zone_of(ctx: AppContext, post: ListPost) -> str:
    if post.account:
        try:
            return ctx.store.accounts.get(post.account).timezone
        except AccountNotFound:
            pass
    return DEFAULT_TIMEZONE


@router.post("/plan/{post_id}/schedule")
def move(request: Request, post_id: str, when: str = Form(...)) -> Response:
    """Move a post to an exact time — read in its own account's zone, as `schedule` does."""
    ctx = ctx_of(request)
    if request.app.state.jobs.busy(RENDER) is not None:
        return done(request, STILL_RENDERING, "warning")
    try:
        at = datetime.fromisoformat(when)
        zone = _zone_of(ctx, ctx.tools.posts.get(post_id))
        when_text = f"{at.astimezone(ZoneInfo(zone)):%Y-%m-%d %H:%M}"
        post = schedule_post(
            ctx.tools.posts, ctx.store.accounts, post_id, when_text, request.app.state.clock()
        )
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e) or f"post {post_id} can't be moved", "error")
    return _moved(request, f"post {post_id} moves to {_fill_line(post)}")


@router.post("/plan/{post_id}/unschedule")
def unschedule(request: Request, post_id: str) -> Response:
    """Take a post off its time; the post itself is kept."""
    ctx = ctx_of(request)
    if request.app.state.jobs.busy(RENDER) is not None:
        return done(request, STILL_RENDERING, "warning")
    try:
        schedule_post(ctx.tools.posts, ctx.store.accounts, post_id, None, request.app.state.clock())
    except ManhwatokError as e:
        return done(request, str(e), "error")
    return done(request, f"post {post_id} is no longer scheduled", changed=["posts"])
