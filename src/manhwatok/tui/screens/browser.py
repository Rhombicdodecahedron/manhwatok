"""A log for a browser job (upload, login) while the user works in the browser window."""

from __future__ import annotations

from typing import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Log, Static

from manhwatok.domain.errors import ManhwatokError

# job(progress) runs in the browser worker and returns the closing line to show.
BrowserJob = Callable[[Callable[[str], None]], str]


class BrowserScreen(Screen[None]):
    DEFAULT_CSS = """
    BrowserScreen #heading { height: 1; padding: 0 1; text-style: bold; }
    BrowserScreen Log { height: 1fr; }
    """
    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self, heading: str, job: BrowserJob) -> None:
        super().__init__()
        self.heading = heading
        self.job = job
        self.running = False

    def compose(self) -> ComposeResult:
        yield Static(self.heading, id="heading", markup=False)
        yield Log(id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.running = self.app.start_browser(self._run)
        if not self.running:
            self.call_later(self.dismiss, None)

    def write(self, line: str) -> None:
        """Add a line to the log; safe from the worker thread."""
        self.app.later(self._write_line, line)

    def _write_line(self, line: str) -> None:
        self.query_one(Log).write_line(line)

    def _run(self) -> None:
        try:
            final = self.job(self.write)
        except ManhwatokError as e:
            self.app.fail(e)
            final = f"error: {e}"
        self.write(final)
        self.write("done — press escape to go back")
        self.app.later(self._finished)

    def _finished(self) -> None:
        self.running = False

    def action_back(self) -> None:
        if self.running:
            self.app.notify(
                "the browser is still open — finish there and answer the question first",
                severity="warning",
            )
            return
        self.dismiss(None)
