"""Posts: the list, a preview of the highlighted post, and what you can do with it."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Static

from manhwatok.app.render_post import rendered_files
from manhwatok.app.songs import song_for
from manhwatok.domain.errors import ManhwatokError, NotRendered
from manhwatok.domain.post import ListPost
from manhwatok.domain.text import plain_title
from manhwatok.tui.text import clip, post_details, post_status
from manhwatok.tui.widgets.dialogs import ChoiceModal
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
