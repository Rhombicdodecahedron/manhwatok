"""Queue: the week ahead of every account's posting slots, day by day, with the posts that
have run past their time on top — and filling, moving and clearing its slots."""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from manhwatok.app.context import AppContext
from manhwatok.app.fill_plan import PlanRow, fill, overdue_rows, plan_rows, schedule_post
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.post import ListPost
from manhwatok.domain.text import plain_title
from manhwatok.tui.screens.browser import BrowserScreen
from manhwatok.tui.screens.posts import upload_in_app
from manhwatok.tui.text import clip, post_status
from manhwatok.tui.widgets.dialogs import ChoiceModal, ConfirmModal
from manhwatok.tui.widgets.headed_table import HeadedTable

DAYS = 7  # how far ahead the queue shows, and fills
HEADING = "heading:"
EMPTY, OVERDUE, NOT_A_SLOT = "empty", "overdue", "not a slot"


def _when(at: datetime) -> str:
    return f"{at:%a %d %b %H:%M}"


class QueueRow(NamedTuple):
    """A row of the table: a slot of the plan (or a post off the slots), or an overdue post."""

    plan: PlanRow
    overdue: bool

    @property
    def post(self) -> ListPost | None:
        return self.plan.post

    @property
    def account(self) -> Account:
        return self.plan.account


def _key(row: PlanRow) -> str:
    if row.post is not None:
        return f"post:{row.post.id}"
    return f"slot:{row.account.handle}:{row.at.isoformat()}"


class QueueTable(HeadedTable):
    """The rows under a heading per day. Enter opens the highlighted post."""

    HEADING = HEADING
    BINDINGS = [Binding("enter", "select_cursor", "Open post")]


class QueuePane(Vertical):
    DEFAULT_CSS = """
    QueuePane QueueTable { height: 1fr; }
    QueuePane #queue-hint { height: auto; color: $text-muted; padding: 0 1; }
    """
    BINDINGS = [
        Binding("f", "fill", "Fill account"),
        Binding("F", "fill_all", "Fill all"),
        Binding("m", "move", "Move"),
        Binding("u", "upload", "Upload"),
        Binding("x", "clear", "Unschedule"),
        Binding("r", "reload", "Refresh"),
    ]

    POLL_SECONDS = 2.0  # how often posts, accounts and the clock are looked at for changes

    def __init__(self) -> None:
        super().__init__()
        self.rows: dict[str, QueueRow] = {}
        self._stamp: tuple | None = None  # what the plan was last read from, to notice changes

    def compose(self) -> ComposeResult:
        yield QueueTable(id="queue-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="queue-hint", markup=False)

    def on_mount(self) -> None:
        self.query_one(QueueTable).add_columns("time", "account", "post", "title", "status", "")
        self.reload()
        self.set_interval(self.POLL_SECONDS, self._poll)

    def _look(self) -> tuple | None:
        """What the plan is read from: the posts on disk, the accounts (their slots) and the
        minute it is — a post runs past its time with nothing else changing."""
        ctx = self.app.ctx
        try:
            accounts = tuple(a.model_dump_json() for a in ctx.store.accounts.list())
            return ctx.tools.posts.stamp(), accounts, f"{self.app.clock():%Y-%m-%d %H:%M}"
        except (ManhwatokError, OSError):
            return None

    def _poll(self) -> None:
        """Read the plan again when it changed: a post scheduled, built or sent from another
        terminal, slots edited there, or a slot's time gone by — the cursor staying put."""
        stamp = self._look()
        if stamp is not None and stamp != self._stamp:
            self.reload()

    def focus_main(self) -> None:
        self.query_one(QueueTable).focus()

    def refresh_data(self) -> None:
        self.reload()

    def action_reload(self) -> None:
        self.reload()

    def reload(self, select: str | None = None) -> None:
        """Read the plan again; keep (or move) the cursor to row `select` or the current one."""
        ctx = self.app.ctx
        keep = select or self.query_one(QueueTable).current_key
        self._stamp = self._look()
        try:
            accounts = ctx.store.accounts.list()
            posts = ctx.tools.posts.list()
        except ManhwatokError as e:
            self.app.fail(e)
            accounts, posts = [], []
        now = self.app.clock()
        late = overdue_rows(accounts, posts, now)
        ahead = plan_rows(accounts, posts, now, DAYS)
        self.rows = {}
        table = self.query_one(QueueTable)
        table.clear()
        if late:
            self._heading(table, "overdue", 0)
            for row in late:
                self._add(table, QueueRow(row, True))
        day = None
        for n, row in enumerate(ahead, 1):
            if row.at.date() != day:  # each row's day in its own account's zone
                day = row.at.date()
                self._heading(table, f"{row.at:%a %d %b}", n)
            self._add(table, QueueRow(row, False))
        if keep in self.rows:
            table.move_cursor(row=table.get_row_index(keep))
        table.skip_headings(1)
        self.query_one("#queue-hint", Static).update(self._hint(accounts))

    @staticmethod
    def _hint(accounts: list[Account]) -> str:
        if any(a.slots for a in accounts):
            return ""
        who = accounts[0].display if accounts else "@<handle>"
        return (
            "no account has slots yet — add them in the Accounts tab (3), with its Slots, "
            f'Rotation and Time zone, or: manhwatok account set {who} --slots "mon 19:00"'
        )

    def _heading(self, table: QueueTable, label: str, n: int) -> None:
        heading = Text(f"── {label} ──", style="bold")
        table.add_row(heading, "", "", "", "", "", key=f"{HEADING}{n}")

    def _add(self, table: QueueTable, row: QueueRow) -> None:
        plan, key = row.plan, _key(row.plan)
        self.rows[key] = row
        at = _when(plan.at) if row.overdue else f"{plan.at:%H:%M}"
        notes = ([OVERDUE] if row.overdue else []) + ([] if plan.on_slot else [NOT_A_SLOT])
        note = Text(" · ".join(notes), style="bold red" if row.overdue else "yellow")
        if plan.post is None:
            empty = Text(EMPTY, style="dim")
            table.add_row(at, plan.account.display, "-", "-", empty, note, key=key)
            return
        post = plan.post
        title = Text(clip(plain_title(post.title) or "(untitled)", 40))
        status = post_status(post, self.app.ctx.tools.posts)
        table.add_row(at, plan.account.display, post.id, title, status, note, key=key)

    def row_keys(self) -> list[str]:
        """Every row's key, headings too, top to bottom."""
        table = self.query_one(QueueTable)
        return [table.row_key_at(n) or "" for n in range(table.row_count)]

    @property
    def current(self) -> QueueRow | None:
        """The highlighted row, or None on a heading (or an empty table)."""
        return self.rows.get(self.query_one(QueueTable).current_key or "")

    def _selected(self) -> QueueRow | None:
        row = self.current
        if row is None:
            self.app.notify("no slot selected", severity="warning")
        return row

    def _selected_post(self) -> tuple[QueueRow, ListPost] | None:
        row = self._selected()
        if row is None:
            return None
        if row.post is None:
            self.app.notify("no post in that slot — press f to fill it", severity="warning")
            return None
        return row, row.post

    # --- open ----------------------------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.action_open()

    def action_open(self) -> None:
        chosen = self._selected_post()
        if chosen is not None:
            self.app.show_post(chosen[1].id)

    # --- fill ----------------------------------------------------------------------------

    def action_fill(self) -> None:
        row = self._selected()
        if row is not None:
            handle = row.account.handle
            self._fill([handle], f"filling @{handle}'s empty slots of the next {DAYS} days…")

    def action_fill_all(self) -> None:
        try:
            handles = [a.handle for a in self.app.ctx.store.accounts.list() if a.slots]
        except ManhwatokError as e:
            self.app.fail(e)
            return
        if not handles:
            self.app.notify(self._hint([]), severity="warning")
            return
        many = f"{len(handles)} accounts" if len(handles) > 1 else f"@{handles[0]}"
        self._fill(handles, f"filling the empty slots of {many} for the next {DAYS} days…")

    def _fill(self, handles: list[str], start: str) -> None:
        """Fill each account's empty slots in the render worker, one account after another. A
        failure is shown and the next account still gets its turn; every post made is shown
        (and the table refreshed) as soon as it exists."""
        app, now = self.app, self.app.clock()

        def made(post: ListPost) -> None:
            # fill stamps the slot as plan_rows gives it: in the account's own zone
            when = _when(post.scheduled_at) if post.scheduled_at else "unscheduled"
            title = plain_title(post.title) or "(untitled)"
            app.notify(f"{when} · @{post.account} · post {post.id} · {title}")
            self.reload()

        def warn(message: str) -> None:
            app.notify(message, severity="warning")

        def job(ctx: AppContext) -> None:
            for handle in handles:
                try:
                    posts = fill(ctx, handle, now, DAYS, warn, lambda p: app.later(made, p))
                except ManhwatokError as e:
                    app.fail(ManhwatokError(f"@{handle}: {e}"))
                    continue
                if posts:
                    count = f"{len(posts)} post{'s' if len(posts) > 1 else ''}"
                    app.notify(f"@{handle}: {count} made and scheduled")
                else:
                    app.notify(f"every slot of @{handle} in the next {DAYS} days has a post")

        if app.start_render_in_context(job, lambda _: self.reload()):
            app.notify(start)

    # --- move and clear ------------------------------------------------------------------

    def action_move(self) -> None:
        chosen = self._selected_post()
        if chosen is None or self.app.refuse_while_rendering():
            return
        row, post = chosen
        account = row.account
        try:
            posts = self.app.ctx.tools.posts.list()
        except ManhwatokError as e:
            self.app.fail(e)
            return
        empty = [
            slot.at
            for slot in plan_rows([account], posts, self.app.clock(), DAYS)
            if slot.post is None
        ]
        if not empty:
            self.app.notify(
                f"{account.display} has no empty slot in the next {DAYS} days", severity="warning"
            )
            return
        choices = [(_when(at), at.isoformat()) for at in empty]

        def moved(value: str | None) -> None:
            if value is None:
                return
            at = datetime.fromisoformat(value)
            self._schedule(post.id, f"{at:%Y-%m-%d %H:%M}", f"post {post.id} moved to {_when(at)}")

        prompt = f"Move post {post.id} ({account.display}) to"
        self.app.push_screen(ChoiceModal(prompt, choices), moved)

    def action_clear(self) -> None:
        chosen = self._selected_post()
        if chosen is None or self.app.refuse_while_rendering():
            return
        pid = chosen[1].id

        def answered(yes: bool | None) -> None:
            if yes:
                self._schedule(pid, None, f"post {pid} is no longer scheduled")

        question = f"Unschedule post {pid}? The post is kept."
        self.app.push_screen(ConfirmModal(question), answered)

    # --- upload --------------------------------------------------------------------------

    def action_upload(self) -> None:
        """`u` uploads the highlighted post, its slot filled into TikTok's own schedule, as
        `u` does in the Posts tab (and `manhwatok upload` in the terminal). One post at a
        time, and only when no other browser window is open."""
        chosen = self._selected_post()
        if chosen is None or self.app.refuse_while_rendering():
            return
        app, post = self.app, chosen[1]
        if app.browser_open:
            app.notify("a browser is already open — finish there first", severity="warning")
            return

        def job(progress) -> str:
            posted = upload_in_app(app, app.ctx, post, progress, debug=False)
            return f"recorded post {post.id} as sent" if posted else "nothing recorded"

        screen = BrowserScreen(f"Upload post {post.id}", job)
        app.push_screen(screen, lambda _: self.reload(select=f"post:{post.id}"))

    def _schedule(self, post_id: str, when: str | None, done: str) -> None:
        """`when` is read in the post's account's zone — the zone its slot was shown in."""
        ctx = self.app.ctx
        try:
            schedule_post(ctx.tools.posts, ctx.store.accounts, post_id, when, self.app.clock())
        except ManhwatokError as e:
            self.app.fail(e)
            return
        self.app.notify(done)
        self.reload(select=f"post:{post_id}")
