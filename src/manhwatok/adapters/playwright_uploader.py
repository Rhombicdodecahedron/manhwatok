"""Assisted upload in a real, visible Chromium window, driven by Playwright.

Each account gets its own persistent browser profile under `profiles_dir`, where the user logs
in to TikTok by hand once (`manhwatok login`). `upload` opens TikTok's upload page in that
profile, attaches the slides and types the caption, then leaves the window open: the user
reviews the post and clicks Post. This adapter never clicks Post, never sees a password and does
nothing to hide that the browser is automated — no stealth plugins, no extra launch arguments,
no fingerprint, proxy or captcha tricks; it only waits between steps like a person would.
Every TikTok URL and selector lives in `tiktok_page.py`."""

from __future__ import annotations

import random
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from manhwatok.adapters.tiktok_page import TikTokPage
from manhwatok.domain.errors import (
    ManhwatokError,
    NotLoggedIn,
    StorageError,
    UploadUnavailable,
)
from manhwatok.ports.uploader import UploadReport

INSTALL_HINT = "upload needs: uv sync --extra upload && uv run playwright install chromium"
POLL_MS = 200  # how often to look again for an element that isn't there yet


def _load_playwright():
    """(sync_playwright, Error), imported only when a browser is needed, so everything else
    in manhwatok works without the `upload` extra."""
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as e:
        raise UploadUnavailable(INSTALL_HINT) from e
    return sync_playwright, Error


def _first_line(error: Exception) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


def _forget_cut_short_calls(context) -> None:
    """The Playwright call a Ctrl-C cut short stays pending in Playwright's event loop, and
    asyncio would print "Task was destroyed but it is pending!" about it on the way out. That
    loop is thrown away with Playwright, so it may report nothing. `_loop` isn't public
    Playwright API; without it the only harm is that noise."""
    loop = getattr(context, "_loop", None)
    if loop is not None:
        loop.set_exception_handler(lambda loop, details: None)


class PlaywrightUploader:
    def __init__(
        self,
        profiles_dir: Path,
        debug_dir: Path,
        page: TikTokPage = TikTokPage(),
        pause: tuple[float, float] = (0.5, 1.5),
        type_delay_ms: tuple[float, float] = (20, 60),
        headless: bool = False,
    ) -> None:
        """`pause`: seconds to wait between steps, picked at random in that range;
        `type_delay_ms`: the same per typed character. `headless` exists for the tests — the
        commands always open a visible window."""
        self._profiles_dir = profiles_dir
        self._debug_dir = debug_dir
        self._page = page
        self._pause_s = pause
        self._type_delay_ms = type_delay_ms
        self._headless = headless
        self._playwright = None
        self._context = None
        self._error: type[Exception] = Exception  # playwright's Error, once it's loaded
        self._interrupted = False  # Ctrl-C while Playwright was at work

    def login(self, handle: str) -> None:
        with self._noting_ctrl_c():
            page = self._open(handle)
            self._goto(page, self._page.login_url)
            self._wait_until_closed()

    def upload(self, handle: str, slides: list[Path], caption: str, debug: bool) -> UploadReport:
        with self._noting_ctrl_c():
            return self._upload(handle, slides, caption, debug)

    def close(self) -> None:
        """Best effort, never raises. A Ctrl-C in the terminal also stops Playwright's driver
        (it shares the terminal's process group), so the browser may no longer answer:
        context.close() then fails, or waits forever when the Ctrl-C cut a Playwright call
        short. Stopping Playwright ends the browser either way."""
        context, playwright = self._context, self._playwright
        interrupted, self._interrupted = self._interrupted, False
        self._context = self._playwright = None
        if context is not None:
            if interrupted:
                _forget_cut_short_calls(context)
            else:
                try:
                    context.close()
                except Exception:
                    pass  # the user already closed the browser, or the driver is gone
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass

    # --- steps ---------------------------------------------------------------------------

    @contextmanager
    def _noting_ctrl_c(self):
        try:
            yield
        except KeyboardInterrupt:
            self._interrupted = True
            raise

    def _upload(self, handle: str, slides: list[Path], caption: str, debug: bool) -> UploadReport:
        page = self._open(handle)
        problems: list[str] = []
        try:
            self._goto(page, self._page.upload_url)
            file_input = self._upload_input(page, handle)
            if file_input is None:
                problems.append("upload button not found — drag the slides in yourself")
            else:
                self._pause(page)
                problem = self._attach(page, file_input, slides)
                if problem:
                    problems.append(problem)
        except self._error as e:
            self.close()
            raise ManhwatokError(
                f"the browser stopped before the slides were attached: {_first_line(e)}"
            ) from e
        except ManhwatokError:
            self.close()
            raise
        attached = not problems
        captioned = False
        try:
            if not attached:
                problems.append("caption not typed — paste caption.txt yourself")
            else:
                if self._find(page, [self._page.editor_ready], self._page.editor_timeout) is None:
                    problems.append("the post editor didn't open — check the browser window")
                captioned = self._type_caption(page, caption)
                if not captioned:
                    problems.append("caption box not found — paste caption.txt yourself")
        except self._error as e:  # e.g. the user closed the window while the caption was typed
            problems.append(f"the browser stopped: {_first_line(e)}")
        report = UploadReport(attached=attached, captioned=captioned, problems=problems)
        if debug and problems:
            report.debug_dir = self._save_debug(page, slides, problems)
        return report

    def _open(self, handle: str):
        """Start Chromium on the account's own profile; returns its first tab."""
        self.close()
        sync_playwright, self._error = _load_playwright()
        profile = self._profiles_dir / handle
        try:
            profile.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StorageError(f"could not create the browser profile {profile}: {e}") from e
        try:
            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                profile, headless=self._headless, viewport=None
            )
        except self._error as e:
            self.close()
            if "Executable doesn't exist" in str(e):
                raise UploadUnavailable(INSTALL_HINT) from e
            raise ManhwatokError(
                f"could not start the browser for @{handle} (is its window already open?): "
                f"{_first_line(e)}"
            ) from e
        pages = self._context.pages
        return pages[0] if pages else self._context.new_page()

    def _goto(self, page, url: str) -> None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self._page.page_timeout * 1000)
        except self._error as e:
            self.close()
            raise ManhwatokError(f"could not open {url}: {_first_line(e)}") from e

    def _pause(self, page) -> None:
        low, high = self._pause_s
        if high > 0:
            page.wait_for_timeout(random.uniform(low, high) * 1000)

    def _find(self, page, selectors: list[str] | tuple[str, ...], timeout: float, visible=True):
        """The first element matching one of `selectors` (tried in order, in every frame of the
        page), waiting up to `timeout` seconds for one to show up; None if none did. Unless
        `visible` is False, hidden elements don't count."""
        only_visible = " >> visible=true" if visible else ""
        deadline = time.monotonic() + timeout
        while True:
            for selector in selectors:
                for frame in page.frames:
                    element = frame.locator(selector + only_visible).first
                    try:
                        if element.count():
                            return element
                    except self._error:
                        if page.is_closed():
                            raise
                        # the frame went away while we looked; try the next one
            if time.monotonic() >= deadline:
                return None
            page.wait_for_timeout(POLL_MS)

    def _upload_input(self, page, handle: str):
        """The upload page's file input, or None if it doesn't show up in time. Raises
        NotLoggedIn when TikTok sends the browser to its login page instead."""
        deadline = time.monotonic() + self._page.page_timeout
        while True:
            if self._page.login_url_marker in page.url:
                raise NotLoggedIn(f"@{handle} is not logged in — run: manhwatok login @{handle}")
            found = self._find(page, [self._page.file_input], 0, visible=False)
            if found is not None or time.monotonic() >= deadline:
                return found
            page.wait_for_timeout(POLL_MS)

    def _attach(self, page, file_input, slides: list[Path]) -> str | None:
        """None once the slides are attached (in order), else what went wrong."""
        try:
            file_input.set_input_files(slides)
        except self._error as e:
            if page.is_closed():
                raise
            return f"couldn't attach the slides ({_first_line(e)}) — drag them in yourself"
        return None

    def _type_caption(self, page, caption: str) -> bool:
        box = self._find(page, self._page.caption_candidates, self._page.caption_timeout)
        if box is None:
            return False
        self._pause(page)
        box.click()
        page.keyboard.press("ControlOrMeta+A")  # TikTok may prefill the box; replace that
        page.keyboard.press("Delete")
        low, high = self._type_delay_ms
        for char in caption.strip():
            page.keyboard.type(char)
            if high > 0:
                page.wait_for_timeout(random.uniform(low, high))
        return True

    def _save_debug(self, page, slides: list[Path], problems: list[str]) -> Path | None:
        """screenshot.png and page.html in <debug_dir>/<post id>-<time>/ (the slides' folder is
        named after the post). Failing to save them is one more problem, not an error."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        folder = self._debug_dir / f"{slides[0].parent.name}-{stamp}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=folder / "screenshot.png", full_page=True)
            (folder / "page.html").write_text(page.content(), encoding="utf-8")
        except (OSError, self._error) as e:
            problems.append(f"couldn't save the debug files: {_first_line(e)}")
            return None
        return folder

    def _wait_until_closed(self) -> None:
        """Block until the user has closed every tab, or the whole browser."""
        while self._context is not None and self._context.pages:
            try:
                self._context.pages[0].wait_for_event("close", timeout=0)
            except self._error:
                return  # the browser went away together with its tabs
