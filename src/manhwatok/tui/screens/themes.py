"""Themes: the saved searches and titles shared by every account."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from manhwatok.app.accounts import add_theme, update_theme
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Sort
from manhwatok.domain.text import plain_title, split_names
from manhwatok.domain.theme import Theme
from manhwatok.tui.text import clip
from manhwatok.tui.widgets.dialogs import ConfirmModal
from manhwatok.tui.widgets.form import FormModal

SORTS = ", ".join(s.value for s in Sort)
LABELS = {
    "title": "Post title (*word* = accent colour)",
    "tags": "Tags (comma-separated, all must match)",
    "genres": "Genres (comma-separated, all must match)",
    "sort": f"Sort ({SORTS})",
    "min_tag_rank": "Min tag rank (0–100)",
}


def theme_texts(theme: Theme) -> dict[str, str]:
    return {
        "title": theme.title,
        "tags": ", ".join(theme.tags),
        "genres": ", ".join(theme.genres),
        "sort": theme.sort.value,
        "min_tag_rank": str(theme.min_tag_rank),
    }


def theme_fields(texts: dict[str, str], before: dict[str, str] | None) -> dict[str, Any]:
    """Theme fields from form text: everything for a new theme (`before` None; blank sort and
    rank get the defaults), only the changed ones for an existing theme."""
    fields: dict[str, Any] = {}
    for name in LABELS:
        text = texts[name].strip()
        if before is not None and texts[name] == before[name]:
            continue
        if name in ("tags", "genres"):
            fields[name] = split_names(text)
        elif name == "sort":
            try:
                fields[name] = Sort((text or Sort.SCORE.value).lower())
            except ValueError:
                raise ManhwatokError(f"sort must be one of {SORTS}") from None
        elif name == "min_tag_rank":
            try:
                fields[name] = int(text or "60")
            except ValueError:
                raise ManhwatokError("min tag rank must be a whole number from 0 to 100") from None
        else:
            fields[name] = text
    return fields


class ThemesPane(Vertical):
    DEFAULT_CSS = """
    ThemesPane DataTable { height: 1fr; }
    ThemesPane #themes-hint { height: 1; color: $text-muted; padding: 0 1; }
    """
    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),  # enter too (a selected row)
        Binding("d", "remove", "Remove"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.themes: dict[str, Theme] = {}

    def compose(self) -> ComposeResult:
        yield DataTable(id="themes-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="themes-hint")

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("theme", "title", "tags", "genres", "sort", "rank")
        self.reload()

    def focus_main(self) -> None:
        self.query_one(DataTable).focus()

    def refresh_data(self) -> None:
        self.reload()

    def reload(self, select: str | None = None) -> None:
        keep = select or self.current_name
        try:
            themes = self.app.ctx.store.themes.list()
        except ManhwatokError as e:
            self.app.fail(e)
            themes = []
        self.themes = {t.name: t for t in themes}
        table = self.query_one(DataTable)
        table.clear()
        for t in themes:
            table.add_row(
                t.name,
                Text(clip(plain_title(t.title), 40)),
                Text(clip(", ".join(t.tags) or "-", 30)),
                Text(clip(", ".join(t.genres) or "-", 30)),
                t.sort.value,
                str(t.min_tag_rank),
                key=t.name,
            )
        if keep in self.themes:
            table.move_cursor(row=table.get_row_index(keep))
        hint = "" if themes else "no themes yet — press a to add one"
        self.query_one("#themes-hint", Static).update(hint)

    @property
    def current_name(self) -> str | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    def _selected(self) -> Theme | None:
        theme = self.themes.get(self.current_name or "")
        if theme is None:
            self.app.notify("no theme selected", severity="warning")
        return theme

    def _warn(self, message: str) -> None:
        self.app.notify(message, severity="warning")

    def action_add(self) -> None:
        ctx = self.app.ctx
        defaults = {"sort": Sort.SCORE.value, "min_tag_rank": "60"}
        fields = [("name", "Theme name, e.g. regression-revenge", "", "")]
        fields += [(name, label, "", defaults.get(name, "")) for name, label in LABELS.items()]

        def save(texts: dict[str, str]) -> Theme:
            f = theme_fields(texts, None)
            names = ctx.names(self._warn)
            return add_theme(
                ctx.store.themes,
                names,
                texts["name"],
                f["tags"],
                f["genres"],
                f["sort"],
                f["min_tag_rank"],
                f["title"],
            )

        self.app.push_screen(FormModal("Add a theme", fields, save), self._saved("added"))

    def action_edit(self) -> None:
        theme = self._selected()
        if theme is None:
            return
        ctx = self.app.ctx
        before = theme_texts(theme)
        fields = [(name, label, before[name], "") for name, label in LABELS.items()]

        def save(texts: dict[str, str]) -> Theme:
            changes = theme_fields(texts, before)
            if not changes:
                return theme
            return update_theme(ctx.store.themes, ctx.names(self._warn), theme.name, changes)

        form = FormModal(f"Edit theme {theme.name}", fields, save)
        self.app.push_screen(form, self._saved("saved"))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.action_edit()

    def _saved(self, verb: str):
        def done(theme: Theme | None) -> None:
            if theme is not None:
                self.app.notify(f"{verb} theme {theme.name}")
                self.reload(select=theme.name)

        return done

    def action_remove(self) -> None:
        theme = self._selected()
        if theme is None:
            return
        name = theme.name

        def remove(yes: bool | None) -> None:
            if not yes:
                return
            try:
                self.app.ctx.store.themes.remove(name)
            except ManhwatokError as e:
                self.app.fail(e)
                return
            self.app.notify(f"removed theme {name}")
            self.reload()

        question = f"Remove theme {name}? Posts built from it stay."
        self.app.push_screen(ConfirmModal(question), remove)
