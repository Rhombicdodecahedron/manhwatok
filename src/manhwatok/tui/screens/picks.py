"""Choose, order and hook a post's titles — for a new post (Build) or an existing one (edit)."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Label, Static
from textual_image.widget import Image

from manhwatok.domain.draft import check_picks
from manhwatok.domain.errors import DraftError
from manhwatok.domain.labels import chapter_label
from manhwatok.domain.models import Manhwa
from manhwatok.domain.post import MAX_ITEMS, PostItem
from manhwatok.domain.text import first_sentence
from manhwatok.tui.text import clip
from manhwatok.tui.widgets.dialogs import ConfirmModal, TextModal
from manhwatok.tui.widgets.slide_preview import readable_image

Picks = tuple[str, list[PostItem]]


class PicksScreen(Screen[Picks | None]):
    """Dismisses with (title, items) on ctrl+s, or None when cancelled."""

    DEFAULT_CSS = """
    PicksScreen #heading { height: 1; padding: 0 1; text-style: bold; }
    PicksScreen #title-row { height: 3; }
    PicksScreen #title-row Label { width: 8; padding: 1 1; }
    PicksScreen #title { width: 1fr; }
    PicksScreen #lists { height: 1fr; }
    PicksScreen #picks-list { width: 3fr; }
    PicksScreen #others-list { width: 2fr; }
    PicksScreen .list Label { padding: 0 1; text-style: bold; }
    PicksScreen DataTable { height: 1fr; }
    PicksScreen #cover-box { width: 1fr; align-horizontal: center; }
    PicksScreen #cover { width: auto; height: 1fr; }
    PicksScreen #cover-info { height: auto; }
    """
    BINDINGS = [
        Binding("space", "toggle", "Pick/unpick"),
        Binding("shift+up", "move(-1)", "Move up"),
        Binding("shift+down", "move(1)", "Move down"),
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self, heading: str, title: str, items: list[PostItem], candidates: list[Manhwa]
    ) -> None:
        super().__init__()
        self.heading = heading
        self.candidates = list(candidates)
        self.items = list(items)
        self.hooks = {m.anilist_id: first_sentence(m.description) for m in self.candidates}
        self.hooks.update({i.manhwa.anilist_id: i.hook for i in self.items})
        self._start: Picks = (title, list(items))
        self._title = title

    def compose(self) -> ComposeResult:
        yield Static(self.heading, id="heading", markup=False)
        with Horizontal(id="title-row"):
            yield Label("Title")
            yield Input(self._title, placeholder="*word* = accent colour", id="title")
        with Horizontal(id="lists"):
            with Vertical(id="picks-list", classes="list"):
                yield Label("Picks  (enter: edit hook)", id="picks-label")
                yield DataTable(id="picks", cursor_type="row")
            with Vertical(id="others-list", classes="list"):
                yield Label("Other candidates")
                yield DataTable(id="others", cursor_type="row")
            with Vertical(id="cover-box"):
                yield Image(id="cover")
                yield Static("", id="cover-info", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#picks", DataTable).add_columns("#", "title", "chapters", "hook")
        self.query_one("#others", DataTable).add_columns("title", "chapters", "hook")
        self._fill()
        self.query_one("#picks" if self.items else "#others", DataTable).focus()

    @property
    def others(self) -> list[Manhwa]:
        picked = {i.manhwa.anilist_id for i in self.items}
        return [m for m in self.candidates if m.anilist_id not in picked]

    @property
    def title_text(self) -> str:
        return self.query_one("#title", Input).value

    def _fill(self, picks_row: int | None = None, others_row: int | None = None) -> None:
        picks = self.query_one("#picks", DataTable)
        others = self.query_one("#others", DataTable)
        picks_row = picks.cursor_row if picks_row is None else picks_row
        others_row = others.cursor_row if others_row is None else others_row
        picks.clear()
        for n, item in enumerate(self.items, 1):
            m = item.manhwa
            picks.add_row(n, clip(m.title, 36), chapter_label(m), item.hook, key=str(m.anilist_id))
        others.clear()
        for m in self.others:
            hook = self.hooks[m.anilist_id]
            others.add_row(clip(m.title, 36), chapter_label(m), hook, key=str(m.anilist_id))
        if picks.row_count:
            picks.move_cursor(row=min(picks_row, picks.row_count - 1))
        if others.row_count:
            others.move_cursor(row=min(others_row, others.row_count - 1))
        self.query_one("#picks-label", Label).update(
            f"Picks {len(self.items)}/{MAX_ITEMS}  (enter: edit hook)"
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table is self.focused:
            self._show_cover(event.data_table)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if isinstance(event.widget, DataTable):
            self._show_cover(event.widget)

    def _show_cover(self, table: DataTable) -> None:
        """The cover (if already on disk) and facts of the title under `table`'s cursor."""
        manhwa = None
        if table.row_count:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            manhwa = next(m for m in self.candidates if str(m.anilist_id) == key)
        cover = self.query_one("#cover", Image)
        path = self.app.ctx.tools.covers.cached(manhwa) if manhwa else None
        if path is not None and not readable_image(path):
            path = None
        cover.image = path
        cover.display = path is not None
        info = ""
        if manhwa is not None:
            score = f"{manhwa.score}%" if manhwa.score is not None else "–"
            info = f"{manhwa.title}\n{chapter_label(manhwa)} · {score}\n{', '.join(manhwa.genres)}"
        self.query_one("#cover-info", Static).update(info)

    def action_toggle(self) -> None:
        focused = self.focused
        if not isinstance(focused, DataTable) or not focused.row_count:
            return
        row = focused.cursor_row
        if focused.id == "picks":
            removed = self.items.pop(row)
            self.hooks[removed.manhwa.anilist_id] = removed.hook
        else:
            if len(self.items) >= MAX_ITEMS:
                self.app.notify(
                    f"a TikTok post fits at most {MAX_ITEMS} titles", severity="warning"
                )
                return
            m = self.others[row]
            self.items.append(PostItem(manhwa=m, hook=self.hooks[m.anilist_id]))
        self._fill()

    def action_move(self, delta: int) -> None:
        picks = self.query_one("#picks", DataTable)
        row = picks.cursor_row
        if self.focused is not picks or not 0 <= row + delta < len(self.items):
            return
        self.items[row], self.items[row + delta] = self.items[row + delta], self.items[row]
        self._fill(picks_row=row + delta)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "picks":
            return
        row = event.cursor_row
        item = self.items[row]

        def entered(hook: str | None) -> None:
            if hook is not None:
                self.items[row] = item.model_copy(update={"hook": hook})
                self._fill()

        self.app.push_screen(TextModal(f"Hook for {item.manhwa.title}", item.hook), entered)

    def action_save(self) -> None:
        if self.app.refuse_while_rendering():
            return
        title = self.title_text.strip()
        try:
            check_picks(title, self.items)
        except DraftError as e:
            self.app.fail(e)
            return
        self.dismiss((title, list(self.items)))

    def action_cancel(self) -> None:
        if (self.title_text, self.items) == self._start:
            self.dismiss(None)
            return

        def answered(yes: bool | None) -> None:
            if yes:
                self.dismiss(None)

        self.app.push_screen(ConfirmModal("Discard your changes?"), answered)
