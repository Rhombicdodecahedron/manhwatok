"""The real PlaywrightUploader in headless Chromium against the fixture pages in tests/fixtures,
served on 127.0.0.1 — never tiktok.com. Temporary profiles, no pauses, no typing delay.
Skipped unless the upload extra and its Chromium are installed:
    uv sync --extra upload && uv run playwright install chromium"""

import functools
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from manhwatok.adapters.playwright_uploader import PlaywrightUploader
from manhwatok.adapters.tiktok_page import TikTokPage
from manhwatok.domain.errors import NotLoggedIn
from manhwatok.ports.uploader import UploadReport

sync_api = pytest.importorskip(
    "playwright.sync_api", reason="needs the upload extra: uv sync --extra upload"
)
pytestmark = pytest.mark.browser

FIXTURES = Path(__file__).parent.parent / "fixtures"
CAPTION = "Manhwa where the MC regresses\n\n1. Doom Breaker\n2. Kubera\n\n#manhwa #webtoon\n"


@pytest.fixture(scope="module", autouse=True)
def _chromium():
    """Skip, not fail, when Playwright's Chromium hasn't been downloaded."""
    try:
        with sync_api.sync_playwright() as p:
            p.chromium.launch(headless=True).close()
    except sync_api.Error as e:
        first = str(e).strip().splitlines()[0]
        pytest.skip(f"needs Chromium: uv run playwright install chromium ({first})")


class _Site(SimpleHTTPRequestHandler):
    """Serves tests/fixtures. Like TikTok, it sends a browser without a session cookie from
    a `?needs-session` page to the login page."""

    def do_GET(self):
        if "needs-session" in self.path and "session=yes" not in self.headers.get("Cookie", ""):
            self.send_response(302)
            self.send_header("Location", "/login.html?redirect_url=/fake_upload.html")
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def site():
    """tests/fixtures over http://127.0.0.1:<free port>."""
    handler = functools.partial(_Site, directory=str(FIXTURES))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join()


def _uploader(
    tmp_path, site, upload="fake_upload.html", cls=PlaywrightUploader, **page_fields
) -> PlaywrightUploader:
    fields = {"page_timeout": 5, "editor_timeout": 0.6, "caption_timeout": 0.3, **page_fields}
    page = TikTokPage(
        login_url=f"{site}/login.html?log-in", upload_url=f"{site}/{upload}", **fields
    )
    return cls(
        tmp_path / "browser",
        tmp_path / "debug",
        page,
        pause=(0, 0),
        type_delay_ms=(0, 0),
        headless=True,
    )


def _slides(tmp_path) -> list[Path]:
    folder = tmp_path / "posts" / "20260914-a3f9"
    folder.mkdir(parents=True)
    slides = [folder / f"0{n}.png" for n in (1, 2, 3)]
    for slide in slides:
        slide.write_bytes(b"png")
    return slides


def _window(uploader):
    """The browser tab the user would be looking at."""
    return uploader._context.pages[0]


def test_attaches_the_slides_in_order_and_types_the_caption(tmp_path, site):
    uploader = _uploader(tmp_path, site)
    try:
        report = uploader.upload("reads", _slides(tmp_path), CAPTION, debug=True)
        window = _window(uploader)
        assert window.locator("#files li").all_inner_texts() == ["01.png", "02.png", "03.png"]
        # The prefilled "01.png" is replaced by the caption, one line per Enter.
        box = window.locator(".caption-editor [contenteditable]")
        lines = box.evaluate("box => Array.from(box.childNodes, line => line.textContent)")
        assert lines == CAPTION.strip().split("\n")
        assert window.evaluate("document.body.dataset.posted") is None  # Post is the user's click
    finally:
        uploader.close()
    assert report == UploadReport(attached=True, captioned=True, problems=[])
    assert (tmp_path / "browser" / "reads").is_dir()
    assert not (tmp_path / "debug").exists()  # nothing was missing


def test_a_missing_caption_box_is_a_problem_not_a_crash(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?no-caption")
    try:
        report = uploader.upload("reads", _slides(tmp_path), CAPTION, debug=False)
    finally:
        uploader.close()
    assert report == UploadReport(
        attached=True,
        captioned=False,
        problems=["caption box not found — paste caption.txt yourself"],
    )


def test_an_editor_that_never_opens_is_a_problem(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?no-editor")
    try:
        report = uploader.upload("reads", _slides(tmp_path), CAPTION, debug=False)
    finally:
        uploader.close()
    assert report.attached is True
    assert report.problems == [
        "the post editor didn't open — check the browser window",
        "caption box not found — paste caption.txt yourself",
    ]


def test_a_page_without_a_file_input_is_a_problem(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?no-input", page_timeout=0.5)
    try:
        report = uploader.upload("reads", _slides(tmp_path), CAPTION, debug=False)
    finally:
        uploader.close()
    assert report == UploadReport(
        attached=False,
        captioned=False,
        problems=[
            "upload button not found — drag the slides in yourself",
            "caption not typed — paste caption.txt yourself",
        ],
    )


def test_not_logged_in_says_how_to_log_in_and_closes_the_browser(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?needs-session")
    try:
        with pytest.raises(NotLoggedIn) as e:
            uploader.upload("reads", _slides(tmp_path), CAPTION, debug=False)
        assert uploader._context is None  # already closed
    finally:
        uploader.close()
    assert str(e.value) == "@reads is not logged in — run: manhwatok login @reads"


class _UserClosesTheWindow(PlaywrightUploader):
    """login() waits for the user to close the window; this "user" closes it right away,
    after noting which page it showed."""

    def _wait_until_closed(self):
        window = self._context.pages[0]
        self.shown = window.url
        window.close()
        super()._wait_until_closed()


def test_a_login_is_kept_in_the_accounts_own_profile(tmp_path, site):
    login = _uploader(tmp_path, site, cls=_UserClosesTheWindow)
    try:
        login.login("reads")
    finally:
        login.close()
    assert login.shown == f"{site}/login.html?log-in"

    uploader = _uploader(tmp_path, site, "fake_upload.html?needs-session")
    try:
        report = uploader.upload("reads", _slides(tmp_path), CAPTION, debug=False)
        assert (report.attached, report.captioned) == (True, True)
        with pytest.raises(NotLoggedIn):  # another account: its own profile, never logged in
            uploader.upload("other", _slides(tmp_path / "other"), CAPTION, debug=False)
    finally:
        uploader.close()


def test_debug_saves_a_screenshot_and_the_page_when_something_is_missing(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?no-caption")
    try:
        report = uploader.upload("reads", _slides(tmp_path), CAPTION, debug=True)
    finally:
        uploader.close()
    [folder] = (tmp_path / "debug").iterdir()
    assert report.debug_dir == folder
    assert re.fullmatch(r"20260914-a3f9-\d{8}-\d{6}", folder.name)  # <post id>-<local time>
    assert (folder / "screenshot.png").read_bytes().startswith(b"\x89PNG")
    assert 'data-e2e="post_video_button"' in (folder / "page.html").read_text()
