"""Pick the picture one title of a post is drawn with.

AniList has a single cover per manhwa, and it is not always the good one. MangaDex usually has
the whole run of volume covers, so this screen lists those and lets you take one — or point the
title at any file or URL of your own. Whatever is chosen lands in the post's folder as that
title's art, exactly as `manhwatok art` would leave it.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Label, Static
from textual_image.widget import Image

from manhwatok.app.art_options import list_art, use_art
from manhwatok.app.item_art import clear_item_art, set_item_art
from manhwatok.app.render_post import render_post
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import ArtSourceName
from manhwatok.ports.art import ArtOption
from manhwatok.tui.text import clip
from manhwatok.tui.widgets.dialogs import TextModal
from manhwatok.tui.widgets.slide_preview import readable_image

ART = "art"  # worker group: looking up what a source has, one title at a time
LABEL_WIDTH = 44  # wide enough for "\u2605 99  1200x1800  by artist_name"


class ArtScreen(Screen[None]):
    DEFAULT_CSS = """
    ArtScreen #heading { height: 1; padding: 0 1; text-style: bold; }
    ArtScreen #columns { height: 1fr; }
    ArtScreen #titles-box { width: 2fr; }
    ArtScreen #covers-box { width: 2fr; }
    ArtScreen #art-box { width: 1fr; align-horizontal: center; }
    ArtScreen Label { padding: 0 1; text-style: bold; }
    ArtScreen DataTable { height: 1fr; }
    ArtScreen #art-preview { width: auto; height: 1fr; }
    ArtScreen #art-info { height: auto; }
    """
    BINDINGS = [
        Binding("s", "switch_source", "Covers/fan art"),
        Binding("u", "from_hand", "File/URL"),
        Binding("c", "clear", "Clear art"),
        Binding("o", "open", "Open picture"),
        Binding("escape", "back", "Back"),
        Binding("q", "back", "Back", show=False),
        Binding("1", "noop", show=False),
        Binding("2", "noop", show=False),
        Binding("3", "noop", show=False),
        Binding("4", "noop", show=False),
    ]

    def __init__(self, post_id: str) -> None:
        super().__init__()
        self.post_id = post_id
        self.options: list[ArtOption] = []
        self.looking_up = False
        self.source_name = ArtSourceName.COVERS
        self.looked_up: int | None = None  # the title the listed options belong to

    def compose(self) -> ComposeResult:
        yield Static(f"Art for post {self.post_id}", id="heading", markup=False)
        with Horizontal(id="columns"):
            with Vertical(id="titles-box"):
                yield Label("Titles  (enter: its covers)")
                yield DataTable(id="titles", cursor_type="row")
            with Vertical(id="covers-box"):
                yield Label(_source_label(ArtSourceName.COVERS), id="covers-label")
                yield DataTable(id="covers", cursor_type="row")
            with Vertical(id="art-box"):
                yield Image(id="art-preview")
                yield Static("", id="art-info", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        titles = self.query_one("#titles", DataTable)
        titles.add_columns("id", "title", "art")
        self.query_one("#covers", DataTable).add_columns("#", "cover")
        self.reload()
        titles.focus()

    # --- what is on screen ---------------------------------------------------------------

    @property
    def source(self):
        """The art source the screen is currently offering."""
        return self.app.ctx.art_sources[self.source_name]

    @property
    def post(self):
        return self.app.ctx.tools.posts.get(self.post_id)

    def reload(self) -> None:
        """Redraw the titles from the saved post, keeping the cursor where it was."""
        table = self.query_one("#titles", DataTable)
        row = table.cursor_row
        table.clear()
        for item in self.post.items:
            table.add_row(
                str(item.manhwa.anilist_id),
                clip(item.manhwa.title, 40),
                item.custom_art or "-",
            )
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
        self._show_art()

    def _selected_id(self) -> int | None:
        table = self.query_one("#titles", DataTable)
        if not table.row_count:
            return None
        return int(str(table.get_row_at(table.cursor_row)[0]))

    def _show_art(self) -> None:
        """Preview the picked art of the highlighted title, when it has one on disk."""
        image = self.query_one("#art-preview", Image)
        info = self.query_one("#art-info", Static)
        path = self.picked_file()
        if path is not None and not readable_image(path):
            path = None
        image.image = path
        image.display = path is not None
        info.update(path.name if path is not None else "no picked art")

    def picked_file(self) -> Path | None:
        anilist_id = self._selected_id()
        if anilist_id is None:
            return None
        item = next((i for i in self.post.items if i.manhwa.anilist_id == anilist_id), None)
        if item is None or not item.custom_art:
            return None
        path = self.app.ctx.tools.posts.folder(self.post_id) / item.custom_art
        return path if path.is_file() else None

    # --- choosing ------------------------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "titles":
            self._look_up()
        else:
            self._use(event.cursor_row)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "titles":
            self._show_art()

    def _look_up(self) -> None:
        """Ask the source what it has for the highlighted title, off the app thread."""
        anilist_id = self._selected_id()
        if anilist_id is None or self.looking_up:
            return
        self.looking_up = True
        self.query_one("#covers", DataTable).clear()
        self.options = []
        app, post_id, source = self.app, self.post_id, self.source

        def run() -> None:
            try:
                found = list_art(post_id, anilist_id, app.ctx.tools, source)
            except ManhwatokError as e:
                app.fail(e)
                app.later(self._looked_up, [])
                return
            app.later(self._looked_up, found)

        self.app.run_worker(run, thread=True, group=ART, name="art")

    def _looked_up(self, found: list[ArtOption]) -> None:
        self.looking_up = False
        self.options = list(found)
        self.looked_up = self._selected_id()
        covers = self.query_one("#covers", DataTable)
        covers.clear()
        if not found:
            self.app.notify(
                f"no {self.source_name} found for that title", severity="warning"
            )
            return
        for number, option in enumerate(found, 1):
            covers.add_row(str(number), clip(option.label, LABEL_WIDTH))
        covers.move_cursor(row=0)
        covers.focus()

    def _use(self, index: int) -> None:
        if not 0 <= index < len(self.options):
            return
        anilist_id = self._selected_id()
        if anilist_id is None:
            return
        option, source = self.options[index], self.source
        self._apply(
            lambda tools: use_art(self.post_id, anilist_id, option, tools, source),
            f"using {option.label} for {anilist_id}",
        )

    def _apply(self, change, done_note: str) -> None:
        """Run `change(tools)` then re-render, in the app's one render worker."""
        post_id = self.post_id

        def job(tools):
            change(tools)
            render_post(post_id, tools)
            return done_note

        def done(note) -> None:
            self.reload()
            self.query_one("#titles", DataTable).focus()
            self.app.notify(str(note))

        self.app.start_render(job, done)

    # --- actions -------------------------------------------------------------------------

    def action_noop(self) -> None:
        """Swallow the app's tab keys, so they don't switch tabs behind this screen."""

    def action_switch_source(self) -> None:
        """Swap publisher covers for fan art and back. Only re-asks once something was listed,
        so switching before a lookup costs no request."""
        self.source_name = (
            ArtSourceName.FANART
            if self.source_name is ArtSourceName.COVERS
            else ArtSourceName.COVERS
        )
        self.query_one("#covers-label", Label).update(_source_label(self.source_name))
        if self.looked_up is not None:
            self._look_up()

    def action_clear(self) -> None:
        anilist_id = self._selected_id()
        if anilist_id is None:
            return
        self._apply(
            lambda tools: clear_item_art(self.post_id, anilist_id, tools),
            f"dropped the picked art for {anilist_id}",
        )

    def action_from_hand(self) -> None:
        anilist_id = self._selected_id()
        if anilist_id is None:
            return

        def answered(given: str | None) -> None:
            if not given or not given.strip():
                return
            self._apply(
                lambda tools: _set_by_hand(self.post_id, anilist_id, given.strip(), tools),
                f"using your own picture for {anilist_id}",
            )

        self.app.push_screen(
            TextModal(f"Picture for {anilist_id}", placeholder="file path or https://…"),
            answered,
        )

    def action_open(self) -> None:
        path = self.picked_file()
        if path is None:
            self.app.notify("that title has no picked art yet", severity="warning")
            return
        try:
            self.app.opener(path)
        except ManhwatokError as e:
            self.app.fail(e)

    def action_back(self) -> None:
        if self.app.rendering:
            self.app.notify("still rendering — try again when it's done", severity="warning")
            return
        self.dismiss(None)


def _source_label(name: ArtSourceName) -> str:
    what = "Covers" if name is ArtSourceName.COVERS else "Fan art"
    return f"{what}  (enter: use, s: swap)"


def _set_by_hand(post_id: str, anilist_id: int, given: str, tools) -> Path:
    """Use a file path or a URL the user typed, the same two ways `manhwatok art` takes one."""
    import tempfile

    from manhwatok.adapters.picture_download import download_picture, looks_like_url

    if not looks_like_url(given):
        return set_item_art(post_id, anilist_id, Path(given).expanduser(), tools)
    with tempfile.TemporaryDirectory(prefix="manhwatok-art-") as scratch:
        got = download_picture(given, Path(scratch))
        return set_item_art(post_id, anilist_id, got, tools)
