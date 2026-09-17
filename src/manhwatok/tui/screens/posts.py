"""Posts: the list, a preview of the highlighted post, and what you can do with it."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Static

from manhwatok.app.delete_post import delete_post
from manhwatok.app.edit_post import update_picks
from manhwatok.app.export_post import export_post
from manhwatok.app.render_post import render_post, rendered_files
from manhwatok.app.songs import set_post_song, song_for
from manhwatok.app.upload_post import upload_post
from manhwatok.domain.errors import ManhwatokError, NotRendered
from manhwatok.domain.post import ListPost
from manhwatok.domain.text import plain_title
from manhwatok.tui.screens.browser import BrowserScreen
from manhwatok.tui.screens.picks import PicksScreen
from manhwatok.tui.text import clip, post_details, post_status
from manhwatok.tui.widgets.dialogs import ChoiceModal, ConfirmModal, TextModal
from manhwatok.tui.widgets.slide_preview import SlidePreview

ALL = "*"


class PostTable(DataTable):
    """Left/right flip the preview's slides instead of scrolling sideways."""

    def action_cursor_left(self) -> None:
        self.query_ancestor(PostsPane).action_slide(-1)

    def action_cursor_right(self) -> None:
        self.query_ancestor(PostsPane).action_slide(1)


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
        Binding("u", "upload", "Upload"),
        Binding("U", "upload(True)", "Upload (debug)", show=False),
        Binding("s", "song", "Song"),
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
        table.add_columns("id", "account", "title", "status", "song", "slides")
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
            songs = {p.id: song_for(p, ctx.store.accounts) for p in posts}
        except ManhwatokError as e:
            self.app.fail(e)
            posts, songs = [], {}
        self.posts = {p.id: p for p in posts}
        table = self.query_one(PostTable)
        table.clear()
        for p in posts:
            table.add_row(
                p.id,
                f"@{p.account}" if p.account else "-",
                clip(plain_title(p.title) or "(untitled)", 40),
                post_status(p, ctx.tools.posts),
                clip(songs[p.id], 24) or "–",
                "-" if p.is_unfinished else str(p.slide_count),
                key=p.id,
            )
        if keep in self.posts:
            table.move_cursor(row=table.get_row_index(keep))
        self.show_post(self.current_id)

    @property
    def current_id(self) -> str | None:
        table = self.query_one(PostTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    @property
    def current(self) -> ListPost | None:
        return self.posts.get(self.current_id or "")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.show_post(event.row_key.value)

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
        try:
            song = song_for(post, ctx.store.accounts)
        except ManhwatokError as e:
            self.app.fail(e)
            song = ""
        details.update(post_details(post, ctx.tools.posts, song))

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

    def _selected(self) -> ListPost | None:
        post = self.current
        if post is None:
            self.app.notify("no post selected", severity="warning")
        return post

    def action_edit(self) -> None:
        post = self._selected()
        if post is None:
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
            )
        except ManhwatokError as e:
            self.app.fail(e)
            return
        self.app.notify(f"exported → {dest}")
        self.reload()

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
            )
            return f"recorded post {pid} as sent" if posted else "nothing recorded"

        heading = f"Upload post {pid}" + (" (debug)" if debug else "")
        app.push_screen(BrowserScreen(heading, job), lambda _: self.reload(select=pid))

    def action_song(self) -> None:
        post = self._selected()
        if post is None:
            return
        ctx, pid = self.app.ctx, post.id
        try:
            account_song = song_for(post.model_copy(update={"song": None}), ctx.store.accounts)
        except ManhwatokError as e:
            self.app.fail(e)
            return
        default = f": {account_song}" if account_song else ", none"
        prefix = "this post has no song of its own — " if post.song == "" else ""
        prompt = f"{prefix}Song for post {pid} — leave empty for the account's{default}"

        def entered(value: str | None) -> None:
            if value is None or value == (post.song or ""):
                return
            try:
                set_post_song(pid, value or None, ctx.tools.posts)
            except ManhwatokError as e:
                self.app.fail(e)
                return
            self.reload(select=pid)

        self.app.push_screen(TextModal(prompt, post.song or "", account_song), entered)

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
                delete_post(pid, self.app.ctx.tools.posts)
            except ManhwatokError as e:
                self.app.fail(e)
                return
            self.app.notify(f"deleted post {pid}")
            self.reload()

        self.app.push_screen(ConfirmModal(f"Delete post {pid} ({size})?"), answered)
