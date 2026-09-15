"""Assisted upload in a real, visible Chromium window, driven by Playwright.

Each account gets its own persistent browser profile under `profiles_dir`, where the user logs
in to TikTok by hand once (`manhwatok login`). `upload` opens TikTok's upload page in that
profile, attaches the slides and types the caption, then leaves the window open: the user
reviews the post and clicks Post. This adapter never clicks Post, never sees a password and does
nothing to hide that the browser is automated — no stealth plugins, no extra launch arguments,
no fingerprint, proxy or captcha tricks; it only waits between steps like a person would.
Every TikTok URL and selector lives in `tiktok_page.py`."""

from __future__ import annotations

from pathlib import Path

from manhwatok.adapters.tiktok_page import TikTokPage
from manhwatok.domain.errors import ManhwatokError, StorageError, UploadUnavailable

INSTALL_HINT = "upload needs: uv sync --extra upload && uv run playwright install chromium"


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

    def login(self, handle: str) -> None:
        page = self._open(handle)
        self._goto(page, self._page.login_url)
        self._wait_until_closed()

    def close(self) -> None:
        context, playwright = self._context, self._playwright
        self._context = self._playwright = None
        if context is not None:
            try:
                context.close()
            except self._error:
                pass  # the user already closed the browser
        if playwright is not None:
            playwright.stop()

    # --- steps ---------------------------------------------------------------------------

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

    def _wait_until_closed(self) -> None:
        """Block until the user has closed every tab, or the whole browser."""
        while self._context is not None and self._context.pages:
            try:
                self._context.pages[0].wait_for_event("close", timeout=0)
            except self._error:
                return  # the browser went away together with its tabs
