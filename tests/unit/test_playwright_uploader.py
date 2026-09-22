"""PlaywrightUploader without a browser: a stand-in for Playwright checks the launch options
and how missing pieces are reported, a stand-in for Chrome the login. tests/browser drives the
real thing."""

import json
import re
import signal
import sys
import time

import pytest

from manhwatok.adapters import playwright_uploader
from manhwatok.adapters.playwright_uploader import PlaywrightUploader
from manhwatok.adapters.tiktok_page import TikTokPage
from manhwatok.domain.errors import ManhwatokError, UploadUnavailable

INSTALL = "upload needs: uv sync --extra upload"
NO_CHROME = "upload needs Google Chrome: https://www.google.com/chrome/"


class FakeError(Exception):
    """Stands in for playwright.sync_api.Error."""


class FakeLocator:
    """Every selector finds an element; clicking it raises the page's `click_error`, if any."""

    def __init__(self, page):
        self.page = page
        self.first = self

    def count(self) -> int:
        return 1

    def set_input_files(self, files):
        pass

    def click(self):
        if self.page.click_error:
            self.page.closed = self.page.click_closes
            raise self.page.click_error


class FakeKeyboard:
    def press(self, key):
        pass

    def type(self, text):
        pass


class FakePage:
    """A browser tab; `goto()` raises `error` if one is given. It is its own only frame."""

    def __init__(self, error: BaseException | None = None):
        self.error = error
        self.url = "about:blank"
        self.closed = False
        self.click_error: Exception | None = None
        self.click_closes = False  # the click_error came with the window closing
        self.frames = [self]
        self.keyboard = FakeKeyboard()

    def goto(self, url, **options):
        if self.error:
            raise self.error
        self.url = url

    def is_closed(self) -> bool:
        return self.closed

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self)

    def wait_for_timeout(self, ms):
        pass

    def screenshot(self, path, **options):
        path.write_bytes(b"png")

    def content(self) -> str:
        return "<html></html>"


class FakeLoop:
    """Playwright's asyncio event loop."""

    def __init__(self):
        self.exception_handler = None

    def set_exception_handler(self, handler):
        self.exception_handler = handler


class FakeContext:
    """The browser with one tab; `close()` raises `close_error` if one is given."""

    def __init__(self, page: FakePage, close_error: Exception | None = None):
        self.page = page
        self.close_error = close_error
        self.closed = 0
        self._loop = FakeLoop()

    @property
    def pages(self) -> list[FakePage]:
        return [] if self.page.closed else [self.page]

    def close(self):
        self.closed += 1
        if self.close_error:
            raise self.close_error


class FakeChromium:
    def __init__(self, error: Exception | None, context: FakeContext | None):
        self.error = error
        self.context = context
        self.launches: list[tuple] = []

    def launch_persistent_context(self, user_data_dir, **options):
        self.launches.append((user_data_dir, options))
        if self.error:
            raise self.error
        return self.context


class FakePlaywright:
    """What sync_playwright().start() returns; every launch fails with `error`, or opens
    `context`. `stop()` raises `stop_error` if one is given."""

    def __init__(self, error=None, context=None, stop_error: Exception | None = None):
        self.chromium = FakeChromium(error, context)
        self.stop_error = stop_error
        self.stopped = 0

    def start(self):
        return self

    def stop(self):
        self.stopped += 1
        if self.stop_error:
            raise self.stop_error


def _fake(monkeypatch, error=None, **kwargs) -> FakePlaywright:
    fake = FakePlaywright(error, **kwargs)
    monkeypatch.setattr(playwright_uploader, "_load_playwright", lambda: (lambda: fake, FakeError))
    return fake


def _uploader(tmp_path, **options) -> PlaywrightUploader:
    return PlaywrightUploader(tmp_path / "browser", tmp_path / "debug", **options)


def _upload(uploader, tmp_path, slides=None, debug=False):
    slides = [tmp_path / "01.png"] if slides is None else slides
    return uploader.upload("reads", slides, "", "caption", None, debug)


def test_without_the_upload_extra_it_says_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright", None)  # makes `import playwright…` fail
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(UploadUnavailable) as e:
        _upload(_uploader(tmp_path), tmp_path)
    assert str(e.value) == INSTALL


@pytest.mark.parametrize(
    ("error", "hint"),
    [
        ("BrowserType.launch_persistent_context: Chromium distribution 'chrome' is not found "
         "at /Applications/Google Chrome.app/Contents/MacOS/Google Chrome", NO_CHROME),
        # Playwright's own Chromium (the browser tests use it) was never downloaded
        ("BrowserType.launch: Executable doesn't exist at /x",
         "upload needs: uv run playwright install chromium"),
    ],
    ids=["chrome", "chromium"],
)
def test_without_the_browser_it_says_how_to_install(tmp_path, monkeypatch, error, hint):
    fake = _fake(monkeypatch, FakeError(error))
    with pytest.raises(UploadUnavailable) as e:
        _upload(_uploader(tmp_path), tmp_path)
    assert str(e.value) == hint
    assert fake.stopped == 1


def test_a_visible_plain_chrome_on_the_accounts_own_profile(tmp_path, monkeypatch):
    fake = _fake(monkeypatch, FakeError("BrowserType.launch_persistent_context: boom\nlogs"))
    with pytest.raises(ManhwatokError) as e:
        _upload(_uploader(tmp_path), tmp_path)
    assert str(e.value) == (
        "could not start the browser for @reads (is its window already open?): "
        "BrowserType.launch_persistent_context: boom"
    )
    # Visible, the user's own window size, and no extra launch arguments of any kind.
    assert fake.chromium.launches == [
        (tmp_path / "browser" / "reads", {"channel": "chrome", "headless": False, "viewport": None})
    ]
    assert (tmp_path / "browser" / "reads").is_dir()
    assert fake.stopped == 1


def test_close_is_safe_without_a_browser(tmp_path):
    uploader = _uploader(tmp_path)
    uploader.close()
    uploader.close()


# A Ctrl-C in the terminal reaches Playwright's driver too (same process group) and kills it;
# the browser can't be asked to close after that — close() must neither raise nor hang.
DRIVER_GONE = Exception("BrowserContext.close: Connection closed while reading from the driver")


def test_close_is_best_effort_once_the_driver_is_gone(tmp_path, monkeypatch):
    context = FakeContext(FakePage(), close_error=DRIVER_GONE)
    fake = _fake(monkeypatch, context=context, stop_error=Exception("Connection closed"))
    uploader = _uploader(tmp_path)
    _upload(uploader, tmp_path)
    uploader.close()
    uploader.close()  # nothing left to close
    assert (context.closed, fake.stopped) == (1, 1)


def test_ctrl_c_stops_playwright_without_asking_the_browser(tmp_path, monkeypatch):
    context = FakeContext(FakePage(error=KeyboardInterrupt()))
    fake = _fake(monkeypatch, context=context)
    uploader = _uploader(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        _upload(uploader, tmp_path)
    uploader.close()
    assert (context.closed, fake.stopped) == (0, 1)  # context.close() could wait forever
    assert context._loop.exception_handler is not None  # no asyncio noise about the cut call

    context.page.error = None  # the next session closes its browser as usual
    _upload(uploader, tmp_path)
    uploader.close()
    assert (context.closed, fake.stopped) == (1, 2)


# login() starts Chrome itself, without Playwright: TikTok won't log in a browser that is
# being automated. This stand-in writes down its arguments, then waits `seconds` and quits.
FAKE_CHROME = """
import json, sys, time
with open(sys.argv[1], "w") as f:
    json.dump(sys.argv[3:], f)
time.sleep(float(sys.argv[2]))
"""


def _fake_chrome(tmp_path, seconds=0.0) -> list[str]:
    return [sys.executable, "-c", FAKE_CHROME, str(tmp_path / "chrome-args.json"), str(seconds)]


def test_login_opens_plain_chrome_on_the_accounts_profile_and_waits_for_it(tmp_path):
    page = TikTokPage(login_url="http://127.0.0.1/login")
    uploader = _uploader(tmp_path, page=page, chrome=_fake_chrome(tmp_path, seconds=0.3))
    started = time.monotonic()
    uploader.login("reads")
    assert time.monotonic() - started >= 0.3
    profile = tmp_path / "browser" / "reads"
    assert profile.is_dir()
    # Playwright starts Chrome with --use-mock-keychain and --password-store=basic; without them
    # here too, Chrome would encrypt the login (Mac keychain, Linux keyring) with a key the
    # upload's Chrome can't read.
    assert json.loads((tmp_path / "chrome-args.json").read_text()) == [
        f"--user-data-dir={profile}",
        "--use-mock-keychain",
        "--password-store=basic",
        "--no-first-run",
        "--no-default-browser-check",
        "http://127.0.0.1/login",
    ]
    uploader.close()


def test_login_without_chrome_says_where_to_get_it(tmp_path, monkeypatch):
    monkeypatch.setattr(playwright_uploader, "CHROME_PATHS", (str(tmp_path / "missing"),))
    monkeypatch.setattr(playwright_uploader.shutil, "which", lambda name: None)
    with pytest.raises(UploadUnavailable) as e:
        _uploader(tmp_path).login("reads")
    assert str(e.value) == NO_CHROME


def test_login_chrome_that_wont_start_is_an_error(tmp_path):
    uploader = _uploader(tmp_path, chrome=[str(tmp_path / "not-chrome")])
    with pytest.raises(ManhwatokError, match="could not start Google Chrome for @reads: "):
        uploader.login("reads")


def test_ctrl_c_during_login_stops_chrome(tmp_path, monkeypatch):
    uploader = _uploader(tmp_path, chrome=_fake_chrome(tmp_path, seconds=30))
    browsers = []
    popen = playwright_uploader.subprocess.Popen

    class Browser(popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            browsers.append(self)

        def wait(self, timeout=None):
            if timeout is None:
                raise KeyboardInterrupt
            return super().wait(timeout)

    monkeypatch.setattr(playwright_uploader.subprocess, "Popen", Browser)
    with pytest.raises(KeyboardInterrupt):
        uploader.login("reads")
    assert browsers[0].returncode == -signal.SIGTERM


def _local_uploader(tmp_path) -> PlaywrightUploader:
    page = TikTokPage(
        login_url="http://127.0.0.1/login", upload_url="http://127.0.0.1/upload", page_timeout=0
    )
    return PlaywrightUploader(
        tmp_path / "browser", tmp_path / "debug", page, pause=(0, 0), type_delay_ms=(0, 0)
    )


@pytest.mark.parametrize(
    ("closes", "problem"),
    [
        # e.g. something lies over the caption box: the window is still there
        (False, "couldn't type the description (Locator.click: Timeout 30000ms exceeded.) — "
         "paste it from caption.txt yourself"),
        (True, "the browser stopped: Locator.click: Timeout 30000ms exceeded."),
    ],
    ids=["window open", "window closed"],
)
def test_a_description_that_cant_be_typed_is_a_problem(tmp_path, monkeypatch, closes, problem):
    window = FakePage()
    window.click_error = FakeError("Locator.click: Timeout 30000ms exceeded.\nCall log: …")
    window.click_closes = closes
    _fake(monkeypatch, context=FakeContext(window))
    uploader = _local_uploader(tmp_path)
    report = _upload(uploader, tmp_path)
    uploader.close()
    assert (report.attached, report.captioned, report.problems) == (True, False, [problem])


def test_debug_files_without_slides_go_to_a_neutral_folder(tmp_path, monkeypatch):
    window = FakePage()
    window.click_error = FakeError("Locator.click: Timeout 30000ms exceeded.")
    _fake(monkeypatch, context=FakeContext(window))
    uploader = _local_uploader(tmp_path)
    report = _upload(uploader, tmp_path, slides=[], debug=True)
    uploader.close()
    assert re.fullmatch(r"upload-\d{8}-\d{6}", report.debug_dir.name)
    assert (report.debug_dir / "page.html").read_text() == "<html></html>"


def test_tiktok_page_defaults():
    page = TikTokPage()
    assert page.upload_url == "https://www.tiktok.com/tiktokstudio/upload?tab=photo"
    assert page.login_url == "https://www.tiktok.com/login"
    assert page.login_url_marker == "/login"
    assert page.file_input == "input[type=file][multiple]"
    assert page.caption_candidates[-2:] == ('[contenteditable="true"]', "textarea")
    assert (page.page_timeout, page.editor_timeout) == (30.0, 60.0)


def test_tiktok_page_visibility_selectors():
    from manhwatok.domain.models import Visibility

    page = TikTokPage()
    assert page.visibility_trigger == (
        '[data-e2e="video_visibility_container"] button[role="combobox"]'
    )
    # The options live in a popup outside the container, and are matched on their visible text:
    # their data-value is not in display order.
    assert page.visibility_choice(Visibility.PRIVATE) == (
        '[role="listbox"] [role="option"]:has(span.TUXText:text-is("Only you"))'
    )
    assert [page.visibility_label(v) for v in Visibility] == ["Everyone", "Friends", "Only you"]
    assert page.shown_visibility("  Friends  ") is Visibility.FRIENDS
    assert page.shown_visibility("Nur du") is None  # TikTok in another language
    assert page.visibility_timeout == 5.0
