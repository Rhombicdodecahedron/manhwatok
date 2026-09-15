"""PlaywrightUploader without a browser: a stand-in for Playwright checks the launch options
and how missing pieces are reported. tests/browser drives the real thing."""

import re
import sys

import pytest

from manhwatok.adapters import playwright_uploader
from manhwatok.adapters.playwright_uploader import PlaywrightUploader
from manhwatok.adapters.tiktok_page import TikTokPage
from manhwatok.domain.errors import ManhwatokError, UploadUnavailable

INSTALL = "upload needs: uv sync --extra upload && uv run playwright install chromium"


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
    """A tab the "user" closes as soon as login() waits for that; `goto()` and
    `wait_for_event()` raise `error` instead if one is given. It is its own only frame."""

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

    def wait_for_event(self, event, **options):
        if self.error:
            raise self.error
        self.closed = True

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


# A Ctrl-C in the terminal reaches Playwright's driver too (same process group) and kills it;
# the browser can't be asked to close after that — close() must neither raise nor hang.
DRIVER_GONE = Exception("BrowserContext.close: Connection closed while reading from the driver")


def test_close_is_best_effort_once_the_driver_is_gone(tmp_path, monkeypatch):
    context = FakeContext(FakePage(), close_error=DRIVER_GONE)
    fake = _fake(monkeypatch, context=context, stop_error=Exception("Connection closed"))
    uploader = _uploader(tmp_path)
    uploader.login("reads")
    uploader.close()
    uploader.close()  # nothing left to close
    assert (context.closed, fake.stopped) == (1, 1)


@pytest.mark.parametrize("command", ["login", "upload"])
def test_ctrl_c_stops_playwright_without_asking_the_browser(tmp_path, monkeypatch, command):
    context = FakeContext(FakePage(error=KeyboardInterrupt()))
    fake = _fake(monkeypatch, context=context)
    uploader = _uploader(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        if command == "login":
            uploader.login("reads")
        else:
            uploader.upload("reads", [tmp_path / "01.png"], "caption", debug=False)
    uploader.close()
    assert (context.closed, fake.stopped) == (0, 1)  # context.close() could wait forever
    assert context._loop.exception_handler is not None  # no asyncio noise about the cut call

    context.page.error = None  # the next session closes its browser as usual
    uploader.login("reads")
    uploader.close()
    assert (context.closed, fake.stopped) == (1, 2)


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
        (False, "couldn't type the caption (Locator.click: Timeout 30000ms exceeded.) — "
         "paste caption.txt yourself"),
        (True, "the browser stopped: Locator.click: Timeout 30000ms exceeded."),
    ],
    ids=["window open", "window closed"],
)
def test_a_caption_that_cant_be_typed_is_a_problem(tmp_path, monkeypatch, closes, problem):
    window = FakePage()
    window.click_error = FakeError("Locator.click: Timeout 30000ms exceeded.\nCall log: …")
    window.click_closes = closes
    _fake(monkeypatch, context=FakeContext(window))
    uploader = _local_uploader(tmp_path)
    report = uploader.upload("reads", [tmp_path / "01.png"], "caption", debug=False)
    uploader.close()
    assert (report.attached, report.captioned, report.problems) == (True, False, [problem])


def test_debug_files_without_slides_go_to_a_neutral_folder(tmp_path, monkeypatch):
    window = FakePage()
    window.click_error = FakeError("Locator.click: Timeout 30000ms exceeded.")
    _fake(monkeypatch, context=FakeContext(window))
    uploader = _local_uploader(tmp_path)
    report = uploader.upload("reads", [], "caption", debug=True)
    uploader.close()
    assert re.fullmatch(r"upload-\d{8}-\d{6}", report.debug_dir.name)
    assert (report.debug_dir / "page.html").read_text() == "<html></html>"


def test_tiktok_page_defaults():
    page = TikTokPage()
    assert page.upload_url == "https://www.tiktok.com/tiktokstudio/upload"
    assert page.login_url == "https://www.tiktok.com/login"
    assert page.login_url_marker == "/login"
    assert page.file_input == "input[type=file]"
    assert page.caption_candidates[-2:] == ('[contenteditable="true"]', "textarea")
    assert (page.page_timeout, page.editor_timeout) == (30.0, 60.0)
