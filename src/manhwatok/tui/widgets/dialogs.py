"""Small modal dialogs: yes/no, one line of text, pick one of a list."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList
from textual.widgets.option_list import Option

DIALOG_CSS = """
ModalScreen { align: center middle; }
.dialog {
    width: 64; height: auto; max-height: 80%;
    border: thick $accent; background: $surface; padding: 1 2;
}
.dialog Label { width: 100%; margin-bottom: 1; }
.dialog .buttons { height: auto; align-horizontal: right; }
.dialog Button { margin-left: 2; }
"""


class ConfirmModal(ModalScreen[bool]):
    """A yes/no question. No is the default: Enter on the focused No, Escape and `n` all say no."""

    DEFAULT_CSS = DIALOG_CSS
    BINDINGS = [
        Binding("y", "answer(True)", "Yes"),
        Binding("n", "answer(False)", "No"),
        Binding("escape", "answer(False)", "No", show=False),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.question, id="question", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Yes", id="yes")
                yield Button("No", id="no", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "yes")

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)


class TextModal(ModalScreen[str | None]):
    """One line of text. Enter returns it (stripped), Escape returns None."""

    DEFAULT_CSS = DIALOG_CSS
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, value: str = "", placeholder: str = "") -> None:
        super().__init__()
        self.prompt, self.value, self.placeholder = prompt, value, placeholder

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.prompt, markup=False)
            yield Input(self.value, placeholder=self.placeholder, id="text")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)


class ChoiceModal(ModalScreen[str | None]):
    """Pick one of `choices` (label, value); Escape returns None."""

    DEFAULT_CSS = DIALOG_CSS
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, choices: list[tuple[str, str]]) -> None:
        super().__init__()
        self.prompt, self.choices = prompt, choices

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.prompt, markup=False)
            yield OptionList(
                *[Option(label, id=value) for label, value in self.choices], markup=False
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)
