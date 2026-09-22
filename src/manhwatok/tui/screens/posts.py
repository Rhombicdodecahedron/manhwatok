"""Posts: the list, a preview of the highlighted post, and what you can do with it."""

from __future__ import annotations

from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Static

from manhwatok.app.context import AppContext
from manhwatok.app.delete_post import delete_post
from manhwatok.app.edit_post import update_picks
from manhwatok.app.export_post import export_post
from manhwatok.app.render_post import choose_cover, render_post, rendered_files
from manhwatok.app.upload_post import schedule_for, sounds_for, upload_post
from manhwatok.domain.account import DEFAULT_TIMEZONE
from manhwatok.domain.errors import AccountNotFound, ManhwatokError, NotRendered
from manhwatok.domain.models import CoverStyle
from manhwatok.domain.post import ListPost
from manhwatok.domain.text import plain_title
from manhwatok.tui.screens.art import ArtScreen
from manhwatok.tui.screens.browser import BrowserScreen
from manhwatok.tui.screens.picks import PicksScreen
from manhwatok.tui.text import clip, post_details, post_status, scheduled_text, sent_text
from manhwatok.tui.widgets.dialogs import ChoiceModal, ConfirmModal
from manhwatok.tui.widgets.headed_table import HeadedTable
from manhwatok.tui.widgets.slide_preview import SlidePreview

ALL = "*"
HEADING = "account:"  # row key prefix of an account's heading row
NO_ACCOUNT = "no account"
MARK = "●"  # what the leading column shows on a marked row

# What a bulk action does to one post; what it returns is the line shown for that post.
BulkFn = Callable[[AppContext, ListPost], str]


class PostTable(HeadedTable):
    """The posts, under a heading per account. Left/right flip the preview's slides instead of
    scrolling sideways, and up/down step over the headings."""

    HEADING = HEADING

    def action_cursor_left(self) -> None:
        self.query_ancestor(PostsPane).action_slide(-1)

    def action_cursor_right(self) -> None:
        self.query_ancestor(PostsPane).action_slide(1)


def _by_account(posts: list[ListPost]) -> list[tuple[str, list[ListPost]]]:
    """The posts under one heading each, accounts alphabetical and the accountless last. Each
    account's posts keep the order they came in (newest first)."""
    groups: dict[str, list[ListPost]] = {}
    for post in posts:
        groups.setdefault(f"@{post.account}" if post.account else NO_ACCOUNT, []).append(post)
    named = sorted((who for who in groups if who != NO_ACCOUNT))
    return [(who, groups[who]) for who in named] + (
        [(NO_ACCOUNT, groups[NO_ACCOUNT])] if NO_ACCOUNT in groups else []
    )


def _render_one(ctx: AppContext, post: ListPost) -> str:
    return f"post {post.id} · {len(render_post(post.id, ctx.tools))} slides"


def upload_in_app(app, ctx: AppContext, post: ListPost, progress, debug: bool) -> bool:
    """Drive the browser for one post — its sound asked for first, unless the account settles
    it on its own (a default sound, or one picked at random), its own planned time filled
    into TikTok's schedule when TikTok would still take it, and who can see it taken from the
    post, or from its account when the post doesn't say (`upload_post`'s own order, so the tabs
    and `manhwatok upload` agree) — and answer whether the user confirmed it went out. Runs in a
    worker: the questions come back from the app. The Queue tab uploads through this too, so
    both tabs upload the same way."""

    def choose_sound(sounds: list[str]) -> str | None:
        choices = [(sound, sound) for sound in sounds] + [("no sound", "")]
        answer = app.choose_from_thread(f"Sound for @{post.account}", choices)
        if app.quitting:
            raise ManhwatokError("upload cancelled — the app is closing")
        return answer or None

    now = app.clock()
    return upload_post(
        post.id,
        ctx.tools.posts,
        ctx.store.accounts,
        ctx.store.history,
        ctx.uploader(),
        app.ask_from_thread,
        progress,
        now=now,
        debug=debug,
        choose_sound=choose_sound,
        themes=ctx.store.themes,
        chapters=ctx.store.chapters,
        schedule_at=schedule_for(post, now),
    )


class PostsPane(Vertical):
    DEFAULT_CSS = """
    PostsPane #posts-table { height: 2fr; }
    PostsPane #preview-row { height: 3fr; }
    PostsPane #preview { width: 2fr; }
    PostsPane #details-box { width: 3fr; padding: 0 1; }
    """
    BINDINGS = [
        Binding("left", "slide(-1)", "◀ slide", show=False),
        Binding("right", "slide(1)", "slide ▶", show=False),
        Binding("o", "open_slide", "Open slide"),
        Binding("e", "edit", "Edit picks"),
        Binding("r", "render", "Render"),
        Binding("x", "export", "Export"),
        Binding("a", "art", "Art"),
        Binding("c", "cover", "Cover"),
        Binding("u", "upload", "Upload"),
        Binding("U", "upload(True)", "Upload (debug)", show=False),
        Binding("d", "delete", "Delete"),
        Binding("f", "filter", "Filter"),
        Binding("space", "mark", "Mark"),
        Binding("ctrl+a", "mark_all", "Mark all", show=False),
        Binding("escape", "unmark_all", "Clear marks", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.account_filter: str | None = None
        self.posts: dict[str, ListPost] = {}
        self.marked: set[str] = set()  # the ids `r`, `x` and `U` act on, when there are any

    def compose(self) -> ComposeResult:
        yield PostTable(id="posts-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="preview-row"):
            yield SlidePreview(id="preview")
            with VerticalScroll(id="details-box"):
                yield Static("", id="details", markup=False)

    def on_mount(self) -> None:
        table = self.query_one(PostTable)
        columns = table.add_columns(
            "", "id", "account", "title", "status", "scheduled", "sent", "slides"
        )
        self.mark_column = columns[0]
        self.reload()

    def focus_main(self) -> None:
        self.query_one(PostTable).focus()

    def refresh_data(self) -> None:
        self.reload()

    def reload(self, select: str | None = None) -> None:
        """Read the posts again; keep (or move) the cursor to `select` or the current post."""
        ctx = self.app.ctx
        keep = select or self.current_id
        try:
            posts = ctx.tools.posts.list()
            if self.account_filter:
                posts = [p for p in posts if p.account == self.account_filter]
            zones = {a.handle: a.timezone for a in ctx.store.accounts.list()}
        except ManhwatokError as e:
            self.app.fail(e)
            posts, zones = [], {}
        self.posts = {p.id: p for p in posts}
        self.marked &= set(self.posts)  # a mark lives only as long as its post is listed
        table = self.query_one(PostTable)
        table.clear()
        for who, theirs in _by_account(posts):
            heading = Text(f"── {who} ──", style="bold")
            table.add_row("", heading, "", "", "", "", "", "", key=HEADING + who)
            for p in theirs:
                zone = zones.get(p.account or "", DEFAULT_TIMEZONE)
                table.add_row(
                    MARK if p.id in self.marked else "",
                    p.id,
                    f"@{p.account}" if p.account else "-",
                    Text(clip(plain_title(p.title) or "(untitled)", 40)),
                    post_status(p, ctx.tools.posts),
                    scheduled_text(p, zone),
                    sent_text(p, zone),
                    "-" if p.is_unfinished else str(p.slide_count),
                    key=p.id,
                )
        if keep in self.posts:
            table.move_cursor(row=table.get_row_index(keep))
        table.skip_headings(1)  # the first row is a heading; start on the post under it
        self.show_post(self.current_id)

    @property
    def current_id(self) -> str | None:
        """The highlighted post's id, or None on an account heading (or an empty table)."""
        return self.query_one(PostTable).current_key

    @property
    def current(self) -> ListPost | None:
        return self.posts.get(self.current_id or "")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.show_post(self.current_id)

    def show_post(self, post_id: str | None) -> None:
        preview = self.query_one(SlidePreview)
        details = self.query_one("#details", Static)
        post = self.posts.get(post_id or "")
        if post is None:
            hint = "no posts for this account" if self.account_filter else "no posts yet"
            preview.show([], f"{hint} — build one in the Build tab (2)")
            details.update("")
            return
        ctx = self.app.ctx
        try:
            slides, _ = rendered_files(post, ctx.tools.posts)
            note = ""
        except NotRendered:
            slides = []
            note = "no picks — press e" if post.is_unfinished else "not rendered — press r"
        preview.show(slides, note)
        details.update(post_details(post, ctx.tools.posts, self._sounds(post)))

    def _sounds(self, post: ListPost) -> list[str]:
        """What `upload` would offer for the post: its theme's sounds, then its account's.
        None for a post without an account (or with one since removed)."""
        if not post.account:
            return []
        try:
            account = self.app.ctx.store.accounts.get(post.account)
        except AccountNotFound:
            return []
        except ManhwatokError as e:
            self.app.fail(e)
            return []
        return sounds_for(post, account, self.app.ctx.store.themes)

    def action_slide(self, delta: int) -> None:
        self.query_one(SlidePreview).step(delta)

    def action_open_slide(self) -> None:
        path = self.query_one(SlidePreview).current
        if path is None:
            self.app.notify("no slide to open", severity="warning")
            return
        try:
            self.app.opener(path)
        except ManhwatokError as e:
            self.app.fail(e)

    def action_filter(self) -> None:
        try:
            accounts = self.app.ctx.store.accounts.list()
        except ManhwatokError as e:
            self.app.fail(e)
            return
        choices = [("all accounts", ALL)] + [(a.display, a.handle) for a in accounts]

        def chosen(value: str | None) -> None:
            if value is not None:
                self.account_filter = None if value == ALL else value
                self.reload()

        self.app.push_screen(ChoiceModal("Show the posts of", choices), chosen)

    # --- marks --------------------------------------------------------------------------

    def action_mark(self) -> None:
        """Mark (or unmark) the post under the cursor: `r`, `x` and `U` then act on the marks
        instead of the cursor. A heading is no post, so it can't be marked."""
        post = self._selected()
        if post is None:
            return
        if post.id in self.marked:
            self.marked.remove(post.id)
        else:
            self.marked.add(post.id)
        self._show_mark(post.id)

    def action_mark_all(self) -> None:
        """Mark every post the filter shows."""
        self.marked = set(self.posts)
        for post_id in self.posts:
            self._show_mark(post_id)

    def action_unmark_all(self) -> None:
        was, self.marked = self.marked, set()
        for post_id in was:
            self._show_mark(post_id)

    def _show_mark(self, post_id: str) -> None:
        mark = MARK if post_id in self.marked else ""
        self.query_one(PostTable).update_cell(post_id, self.mark_column, mark)

    def _marked(self) -> list[ListPost]:
        """The marked posts, in the order the table shows them; empty when nothing is marked."""
        table = self.query_one(PostTable)
        keys = (table.row_key_at(row) for row in range(table.row_count))
        return [self.posts[key] for key in keys if key in self.marked]

    def _bulk(self, doing: str, did: str, posts: list[ListPost], one: BulkFn) -> None:
        """Run `one` over `posts` in one render job, in the order shown: a notification per post
        as it lands, a failure noted and the rest carried on with, and one summary at the end
        ("rendered 2, 1 failed: <id> <why>")."""
        app = self.app

        def job(ctx: AppContext) -> tuple[str, int]:
            count, failed = 0, []
            for post in posts:
                try:
                    ctx.tools.progress(one(ctx, post))
                    count += 1
                except ManhwatokError as e:
                    failed.append(f"{post.id} {e}")
                    ctx.tools.progress(f"post {post.id} failed: {e}")
            summary = f"{did} {count}"
            if failed:
                summary += f", {len(failed)} failed: " + "; ".join(failed)
            return summary, len(failed)

        def finished(result) -> None:
            summary, failures = result
            app.notify(summary, severity="warning" if failures else "information", timeout=8)
            self.reload()

        if app.start_render_in_context(job, finished):
            app.notify(f"{doing} {len(posts)} posts…")

    # --- actions on the marked posts, or on the highlighted one --------------------------

    def _refuse_chapter(self, post: ListPost, why: str) -> bool:
        """True when this action makes no sense for a chapter post, having said so."""
        if post.chapter is None:
            return False
        self.app.notify(f"post {post.id} is a chapter post — it {why}", severity="warning")
        return True

    def _selected(self) -> ListPost | None:
        post = self.current
        if post is None:
            self.app.notify("no post selected", severity="warning")
        return post

    def action_edit(self) -> None:
        post = self._selected()
        if post is None:
            return
        if self._refuse_chapter(post, "has no picks to edit"):
            return
        if self.app.refuse_while_rendering():
            return
        pid = post.id

        def rendered(slides) -> None:
            self.app.notify(f"post {pid} saved · {len(slides)} slides")
            self.reload(select=pid)

        def picked(result) -> None:
            if result is None:
                return
            title, items = result
            self.app.start_render(lambda tools: update_picks(pid, title, items, tools), rendered)

        screen = PicksScreen(f"Edit post {pid}", post.title, post.items, post.candidates)
        self.app.push_screen(screen, picked)

    def action_render(self) -> None:
        marked = self._marked()
        if marked:
            self._bulk("rendering", "rendered", marked, _render_one)
            return
        post = self._selected()
        if post is None:
            return
        pid = post.id

        def rendered(slides) -> None:
            self.app.notify(f"post {pid} · {len(slides)} slides")
            self.reload(select=pid)

        if self.app.start_render(lambda tools: render_post(pid, tools), rendered):
            self.app.notify(f"rendering {pid}…")

    def action_export(self) -> None:
        marked = self._marked()
        if marked:
            self._bulk("exporting", "exported", marked, self._export_one)
            return
        post = self._selected()
        if post is None:
            return
        if self.app.refuse_while_rendering():
            return
        try:
            line = self._export_one(self.app.ctx, post)
        except ManhwatokError as e:
            self.app.fail(e)
            return
        self.app.notify(line)
        self.reload()

    def _export_one(self, ctx: AppContext, post: ListPost) -> str:
        dest = export_post(
            post.id,
            ctx.tools.posts,
            ctx.store.history,
            ctx.settings.export_dir,
            now=self.app.clock(),
            chapters=ctx.store.chapters,
        )
        return f"exported → {dest}"

    def action_art(self) -> None:
        post = self._selected()
        if post is None:
            return
        if self._refuse_chapter(post, "draws its own panels"):
            return
        if post.is_unfinished:
            self.app.notify("that post has no titles yet", severity="warning")
            return
        if self.app.refuse_while_rendering():
            return
        pid = post.id
        self.app.push_screen(ArtScreen(pid), lambda _: self.reload(select=pid))

    def action_cover(self) -> None:
        """Pick the cover version: swapped into 01.png at once when a render already drew it,
        else rendered with it."""
        post = self._selected()
        if post is None:
            return
        if self._refuse_chapter(post, "has one cover, naming the chapter"):
            return
        if self.app.refuse_while_rendering():
            return
        pid = post.id
        about = {
            CoverStyle.FAN: "three covers fanned out",
            CoverStyle.QUAD: "four characters, one per quadrant",
            CoverStyle.HERO: "the first pick's art, full screen",
        }
        choices = [
            (f"{s.value} — {about[s]}" + (" (current)" if s is post.cover else ""), s.value)
            for s in CoverStyle
        ]

        def rendered(slides) -> None:
            self.app.notify(f"post {pid} · {len(slides)} slides")
            self.reload(select=pid)

        def chosen(value: str | None) -> None:
            if value is None:
                return
            style = CoverStyle(value)
            try:
                choose_cover(pid, style, self.app.ctx.tools)
            except NotRendered:
                if self.app.start_render(lambda tools: render_post(pid, tools), rendered):
                    self.app.notify(f"rendering {pid} with the {style.value} cover…")
                return
            except ManhwatokError as e:
                self.app.fail(e)
                return
            self.app.notify(f"post {pid} · {style.value} cover")
            self.reload(select=pid)

        self.app.push_screen(ChoiceModal(f"Cover for post {pid}", choices), chosen)

    def action_upload(self, debug: bool = False) -> None:
        """`u` uploads the post under the cursor, with its log screen; `U` does the same in
        debug, and over every marked post in turn when there are marks."""
        marked = self._marked() if debug else []
        if marked:
            if self._refuse_browser():
                return
            self._bulk("uploading", "uploaded", marked, self._upload_marked)
            return
        post = self._selected()
        if post is None:
            return
        if self.app.refuse_while_rendering() or self._refuse_browser():
            return
        app, pid = self.app, post.id

        def job(progress) -> str:
            posted = self._upload_one(app.ctx, post, progress, debug)
            return f"recorded post {pid} as sent" if posted else "nothing recorded"

        heading = f"Upload post {pid}" + (" (debug)" if debug else "")
        app.push_screen(BrowserScreen(heading, job), lambda _: self.reload(select=pid))

    def _refuse_browser(self) -> bool:
        """True (and warns) while a browser window is already open for another post."""
        if self.app.browser_open:
            self.app.notify("a browser is already open — finish there first", severity="warning")
            return True
        return False

    def _upload_marked(self, ctx: AppContext, post: ListPost) -> str:
        sent = self._upload_one(ctx, post, ctx.tools.progress, debug=True)
        return f"post {post.id} " + ("sent" if sent else "not recorded")

    def _upload_one(self, ctx: AppContext, post: ListPost, progress, debug: bool) -> bool:
        return upload_in_app(self.app, ctx, post, progress, debug)

    def action_delete(self) -> None:
        post = self._selected()
        if post is None:
            return
        if self.app.refuse_while_rendering():
            return
        pid = post.id
        size = "draft" if post.is_unfinished else f"{post.slide_count} slides"

        def answered(yes: bool | None) -> None:
            if not yes:
                return
            try:
                delete_post(pid, self.app.ctx.tools.posts, self.app.ctx.store.chapters)
            except ManhwatokError as e:
                self.app.fail(e)
                return
            self.app.notify(f"deleted post {pid}")
            self.reload()

        self.app.push_screen(ConfirmModal(f"Delete post {pid} ({size})?"), answered)
