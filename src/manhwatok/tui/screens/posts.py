"""Posts: the list, a preview of the highlighted post, and what you can do with it."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Static

from manhwatok.app.delete_post import delete_post
from manhwatok.app.edit_post import update_picks
from manhwatok.app.export_post import export_post
from manhwatok.app.render_post import choose_cover, render_post, rendered_files
from manhwatok.app.upload_post import sounds_for, upload_post
from manhwatok.domain.errors import AccountNotFound, ManhwatokError, NotRendered
from manhwatok.domain.models import CoverStyle
from manhwatok.domain.post import ListPost
from manhwatok.domain.text import plain_title
from manhwatok.tui.screens.art import ArtScreen
from manhwatok.tui.screens.browser import BrowserScreen
from manhwatok.tui.screens.picks import PicksScreen
from manhwatok.tui.text import clip, post_details, post_status
from manhwatok.tui.widgets.dialogs import ChoiceModal, ConfirmModal
from manhwatok.tui.widgets.slide_preview import SlidePreview

ALL = "*"
HEADING = "account:"  # row key prefix of an account's heading row
NO_ACCOUNT = "no account"


class PostTable(DataTable):
    """The posts, under a heading per account. Left/right flip the preview's slides instead of
    scrolling sideways, and up/down step over the headings."""

    def action_cursor_left(self) -> None:
        self.query_ancestor(PostsPane).action_slide(-1)

    def action_cursor_right(self) -> None:
        self.query_ancestor(PostsPane).action_slide(1)

    def action_cursor_down(self) -> None:
        super().action_cursor_down()
        self.skip_headings(1)

    def action_cursor_up(self) -> None:
        super().action_cursor_up()
        self.skip_headings(-1)

    def row_key_at(self, row: int) -> str | None:
        return self.coordinate_to_cell_key(Coordinate(row, 0)).row_key.value

    def skip_headings(self, step: int) -> None:
        """Move on from a heading in the direction of travel, or back the other way when there
        is nothing that way — a heading is a label, never a selection."""
        for way in (step, -step):
            row = self.cursor_row
            while 0 <= row < self.row_count and (self.row_key_at(row) or "").startswith(HEADING):
                row += way
            if 0 <= row < self.row_count:
                self.move_cursor(row=row)
                return


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
    ]

    def __init__(self) -> None:
        super().__init__()
        self.account_filter: str | None = None
        self.posts: dict[str, ListPost] = {}

    def compose(self) -> ComposeResult:
        yield PostTable(id="posts-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="preview-row"):
            yield SlidePreview(id="preview")
            with VerticalScroll(id="details-box"):
                yield Static("", id="details", markup=False)

    def on_mount(self) -> None:
        table = self.query_one(PostTable)
        table.add_columns("id", "account", "title", "status", "slides")
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
        except ManhwatokError as e:
            self.app.fail(e)
            posts = []
        self.posts = {p.id: p for p in posts}
        table = self.query_one(PostTable)
        table.clear()
        for who, theirs in _by_account(posts):
            table.add_row(Text(f"── {who} ──", style="bold"), "", "", "", "", key=HEADING + who)
            for p in theirs:
                table.add_row(
                    p.id,
                    f"@{p.account}" if p.account else "-",
                    Text(clip(plain_title(p.title) or "(untitled)", 40)),
                    post_status(p, ctx.tools.posts),
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
        table = self.query_one(PostTable)
        if not table.row_count:
            return None
        key = table.row_key_at(table.cursor_row)
        return None if (key or "").startswith(HEADING) else key

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

    # --- actions on the highlighted post ------------------------------------------------

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
        post = self._selected()
        if post is None:
            return
        if self.app.refuse_while_rendering():
            return
        ctx = self.app.ctx
        try:
            dest = export_post(
                post.id,
                ctx.tools.posts,
                ctx.store.history,
                ctx.settings.export_dir,
                now=self.app.clock(),
                chapters=ctx.store.chapters,
            )
        except ManhwatokError as e:
            self.app.fail(e)
            return
        self.app.notify(f"exported → {dest}")
        self.reload()

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
        post = self._selected()
        if post is None:
            return
        if self.app.refuse_while_rendering():
            return
        if self.app.browser_open:
            self.app.notify("a browser is already open — finish there first", severity="warning")
            return
        app, pid = self.app, post.id

        def choose_sound(sounds: list[str]) -> str | None:
            choices = [(sound, sound) for sound in sounds] + [("no sound", "")]
            answer = app.choose_from_thread(f"Sound for @{post.account}", choices)
            if app.quitting:
                raise ManhwatokError("upload cancelled — the app is closing")
            return answer or None

        def job(progress) -> str:
            ctx = app.ctx
            posted = upload_post(
                pid,
                ctx.tools.posts,
                ctx.store.accounts,
                ctx.store.history,
                ctx.uploader(),
                app.ask_from_thread,
                progress,
                now=app.clock(),
                debug=debug,
                choose_sound=choose_sound,
                themes=ctx.store.themes,
                chapters=ctx.store.chapters,
            )
            return f"recorded post {pid} as sent" if posted else "nothing recorded"

        heading = f"Upload post {pid}" + (" (debug)" if debug else "")
        app.push_screen(BrowserScreen(heading, job), lambda _: self.reload(select=pid))

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
