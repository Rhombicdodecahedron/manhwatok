"""PlaywrightUploader without a browser: a stand-in for Playwright checks the launch options
and how missing pieces are reported. tests/browser drives the real thing."""

import sys

import pytest

from manhwatok.adapters import playwright_uploader
from manhwatok.adapters.playwright_uploader import PlaywrightUploader
from manhwatok.adapters.tiktok_page import TikTokPage
from manhwatok.domain.errors import ManhwatokError, UploadUnavailable

INSTALL = "upload needs: uv sync --extra upload && uv run playwright install chromium"


class FakeError(Exception):
    """Stands in for playwright.sync_api.Error."""


class FakeChromium:
    def __init__(self, error: Exception):
        self.error = error
        self.launches: list[tuple] = []

    def launch_persistent_context(self, user_data_dir, **options):
        self.launches.append((user_data_dir, options))
        raise self.error


class FakePlaywright:
    """What sync_playwright().start() returns; every launch fails with `error`."""

    def __init__(self, error: Exception):
        self.chromium = FakeChromium(error)
        self.stopped = 0

    def start(self):
        return self

    def stop(self):
        self.stopped += 1


def _fake(monkeypatch, error: Exception) -> FakePlaywright:
    fake = FakePlaywright(error)
    monkeypatch.setattr(playwright_uploader, "_load_playwright", lambda: (lambda: fake, FakeError))
    return fake


def _uploader(tmp_path) -> PlaywrightUploader:
    return PlaywrightUploader(tmp_path / "browser", tmp_path / "debug")


def test_without_the_upload_extra_it_says_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright", None)  # makes `import playwright…` fail
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(UploadUnavailable) as e:
        _uploader(tmp_path).login("reads")
    assert str(e.value) == INSTALL


def test_without_chromium_it_says_how_to_install(tmp_path, monkeypatch):
    fake = _fake(monkeypatch, FakeError("BrowserType.launch: Executable doesn't exist at /x"))
    with pytest.raises(UploadUnavailable) as e:
        _uploader(tmp_path).login("reads")
    assert str(e.value) == INSTALL
    assert fake.stopped == 1


def test_a_visible_plain_chromium_on_the_accounts_own_profile(tmp_path, monkeypatch):
    fake = _fake(monkeypatch, FakeError("BrowserType.launch_persistent_context: boom\nlogs"))
    with pytest.raises(ManhwatokError) as e:
        _uploader(tmp_path).login("reads")
    assert str(e.value) == (
        "could not start the browser for @reads (is its window already open?): "
        "BrowserType.launch_persistent_context: boom"
    )
    # Visible, the user's own window size, and no extra launch arguments of any kind.
    assert fake.chromium.launches == [
        (tmp_path / "browser" / "reads", {"headless": False, "viewport": None})
    ]
    assert (tmp_path / "browser" / "reads").is_dir()
    assert fake.stopped == 1


def test_close_is_safe_without_a_browser(tmp_path):
    uploader = _uploader(tmp_path)
    uploader.close()
    uploader.close()


def test_tiktok_page_defaults():
    page = TikTokPage()
    assert page.upload_url == "https://www.tiktok.com/tiktokstudio/upload"
    assert page.login_url == "https://www.tiktok.com/login"
    assert page.login_url_marker == "/login"
    assert page.file_input == "input[type=file]"
    assert page.caption_candidates[-2:] == ('[contenteditable="true"]', "textarea")
    assert (page.page_timeout, page.editor_timeout) == (30.0, 60.0)
