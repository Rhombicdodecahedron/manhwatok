"""The manhwatok terminal app: one tab per area, one render at a time, one browser at a time."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane
from textual.worker import Worker, WorkerState

from manhwatok.app.context import AppContext, open_context
from manhwatok.app.post_tools import PostTools
from manhwatok.config import Settings
from manhwatok.domain.errors import ManhwatokError
from manhwatok.tui.screens.posts import PostsPane
from manhwatok.tui.widgets.dialogs import ConfirmModal

RENDER, BROWSER = "render", "browser"  # worker groups the app waits for before quitting


def open_file(path: Path) -> None:
    """Open a file in the desktop's default viewer."""
    try:
        subprocess.Popen(
            ["xdg-open", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        raise ManhwatokError(f"no image viewer found (xdg-open): {e}") from e


class ManhwatokApp(App[None]):
    TITLE = "manhwatok"
    CSS = """
    TabbedContent, TabPane { height: 1fr; }
    """
    BINDINGS = [
        Binding("1", "tab('posts')", "Posts"),
        Binding("2", "tab('build')", "Build"),
        Binding("3", "tab('accounts')", "Accounts"),
        Binding("4", "tab('themes')", "Themes"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        ctx: AppContext,
        opener: Callable[[Path], None] = open_file,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        super().__init__()
        self.ctx = ctx
        self.opener = opener
        self.clock = clock
        self._quitting = False
        self._open_question: ConfirmModal | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="posts", id="tabs"):
            with TabPane("Posts", id="posts"):
                yield PostsPane()
            with TabPane("Build", id="build"):
                yield Static("build")
            with TabPane("Accounts", id="accounts"):
                yield Static("accounts")
            with TabPane("Themes", id="themes"):
                yield Static("themes")
        yield Footer()

    def on_mount(self) -> None:
        self._focus_pane("posts")

    def action_tab(self, tab: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self._focus_pane(event.pane.id)

    def _focus_pane(self, tab: str | None) -> None:
        """Put the keyboard in the tab's main widget, so its keys work right away."""
        pane = self.query_one(f"#{tab}", TabPane).children[0]
        focus_main = getattr(pane, "focus_main", None)
        if focus_main is not None:
            focus_main()

    def fail(self, error: Exception) -> None:
        """Show an expected failure; safe to call from any thread."""
        self.notify(str(error), title="error", severity="error", timeout=8)

    # --- one render at a time ------------------------------------------------------------

    @property
    def rendering(self) -> bool:
        return self._busy(RENDER)

    def start_render(
        self, job: Callable[[PostTools], object], done: Callable[[object], None]
    ) -> bool:
        """Run `job(tools)` in the render worker (render progress becomes notifications), then
        `done(result)` on the app thread. A ManhwatokError is shown and `done` isn't called.
        Returns False (and does nothing) while another render is running."""
        if self.rendering:
            self.notify("still rendering — try again when it's done", severity="warning")
            return False
        self._render(job, done)
        return True

    def _render(self, job: Callable[[PostTools], object], done: Callable[[object], None]) -> None:
        def run() -> None:
            tools = replace(self.ctx.tools, progress=lambda msg: self.notify(msg))
            try:
                result = job(tools)
            except ManhwatokError as e:
                self.fail(e)
                return
            self.call_from_thread(done, result)

        self.run_worker(run, thread=True, group=RENDER, name="render")

    # --- one browser at a time -----------------------------------------------------------

    @property
    def browser_open(self) -> bool:
        return self._busy(BROWSER)

    def start_browser(self, job: Callable[[], None]) -> bool:
        """Run `job()` (a login or upload) in the browser worker. The job reports its own
        errors. Returns False while another browser job is running."""
        if self.browser_open:
            self.notify("a browser is already open — finish there first", severity="warning")
            return False
        self.run_worker(job, thread=True, group=BROWSER, name="browser")
        return True

    def ask_from_thread(self, question: str) -> bool:
        """Ask a yes/no question from a worker thread and wait for the answer. Quitting the
        app answers no."""
        answered = threading.Event()
        answer = [False]

        def show() -> None:
            if self._quitting:
                answered.set()
                return
            modal = ConfirmModal(question)

            def done(yes: bool | None) -> None:
                self._open_question = None
                answer[0] = bool(yes)
                answered.set()

            self._open_question = modal
            self.push_screen(modal, done)

        self.call_from_thread(show)
        while not answered.wait(0.2):
            if not self.is_running:
                return False
        return answer[0]

    # --- quitting ------------------------------------------------------------------------

    def _busy(self, group: str) -> bool:
        return any(w.group == group and not w.is_finished for w in self.workers)

    async def action_quit(self) -> None:
        if not (self.rendering or self.browser_open):
            self.exit()
            return
        self._quitting = True
        if self._open_question is not None:
            self._open_question.dismiss(False)
        self.notify("closing — waiting for the browser or the render to finish…")

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state in (WorkerState.PENDING, WorkerState.RUNNING):
            return
        if self._quitting and not (self.rendering or self.browser_open):
            self.exit()


def run(settings: Settings) -> None:
    ctx = open_context(settings)
    try:
        ManhwatokApp(ctx).run()
    finally:
        ctx.close()
