"""A modal form of labelled text fields that saves itself in a worker (names are checked
against AniList) and closes only once saving worked."""

from __future__ import annotations

from typing import Callable, Generic, TypeVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from manhwatok.domain.errors import ManhwatokError

T = TypeVar("T")

# (field name, label, starting value, placeholder)
Field = tuple[str, str, str, str]


class FormModal(ModalScreen[T | None], Generic[T]):
    """`save(values)` gets every field's text and returns the saved object, or raises
    ManhwatokError (shown; the form stays open). Escape cancels."""

    DEFAULT_CSS = """
    FormModal { align: center middle; }
    FormModal #form {
        width: 80; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    FormModal #form-title { text-style: bold; margin-bottom: 1; }
    FormModal .form-label { color: $text-muted; }
    FormModal .buttons { height: auto; align-horizontal: right; margin-top: 1; }
    FormModal Button { margin-left: 2; }
    """
    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title: str, fields: list[Field], save: Callable[[dict[str, str]], T]):
        super().__init__()
        self.form_title = title
        self.fields = fields
        self.save = save
        self.saving = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="form"):
            yield Label(self.form_title, id="form-title")
            for name, label, value, placeholder in self.fields:
                yield Label(label, classes="form-label")
                yield Input(value, placeholder=placeholder, id=f"field-{name}")
            with Horizontal(classes="buttons"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")

    @property
    def values(self) -> dict[str, str]:
        return {name: self.query_one(f"#field-{name}", Input).value for name, *_ in self.fields}

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "save":
            self.action_save()
        else:
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.focus_next()

    def action_save(self) -> None:
        if self.saving:
            return
        self.saving = True
        values = self.values

        def run() -> None:
            try:
                saved = self.save(values)
            except ManhwatokError as e:
                self.app.fail(e)
                self.app.later(setattr, self, "saving", False)
                return
            self.app.later(self.dismiss, saved)

        self.run_worker(run, thread=True, group="form-save")

    def action_cancel(self) -> None:
        if not self.saving:
            self.dismiss(None)
