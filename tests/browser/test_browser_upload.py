"""The real PlaywrightUploader in headless Chromium against the fixture pages in tests/fixtures,
served on 127.0.0.1 — never tiktok.com. Temporary profiles, no pauses, no typing delay.
Skipped unless the upload extra and its Chromium are installed:
    uv sync --extra upload && uv run playwright install chromium
The login test uses the installed Google Chrome instead, and is skipped without it."""

import functools
import re
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from manhwatok.adapters.playwright_uploader import PlaywrightUploader, _find_chrome
from manhwatok.adapters.tiktok_page import TikTokPage
from manhwatok.domain.errors import NotLoggedIn
from manhwatok.ports.uploader import UploadReport

sync_api = pytest.importorskip(
    "playwright.sync_api", reason="needs the upload extra: uv sync --extra upload"
)
pytestmark = pytest.mark.browser

FIXTURES = Path(__file__).parent.parent / "fixtures"
TITLE = "Manhwa where the MC regresses 🔥⏳"
DESCRIPTION = "1. Doom Breaker\n2. Kubera\n\n#manhwa #webtoon"


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
    tmp_path, site, upload="fake_upload.html", options=None, **page_fields
) -> PlaywrightUploader:
    fields = {"page_timeout": 5, "editor_timeout": 0.6, "caption_timeout": 0.3, **page_fields}
    page = TikTokPage(
        login_url=f"{site}/login.html?log-in", upload_url=f"{site}/{upload}", **fields
    )
    return PlaywrightUploader(
        tmp_path / "browser",
        tmp_path / "debug",
        page,
        pause=(0, 0),
        type_delay_ms=(0, 0),
        headless=True,
        **(options or {"channel": None}),
    )


def _slides(tmp_path) -> list[Path]:
    folder = tmp_path / "posts" / "20260914-a3f9"
    folder.mkdir(parents=True)
    slides = [folder / f"0{n}.png" for n in (1, 2, 3)]
    for slide in slides:
        slide.write_bytes(b"png")
    return slides


def _upload(uploader, slides, debug=False, handle="reads", sound="solo leveling"):
    return uploader.upload(handle, slides, TITLE, DESCRIPTION, sound, debug)


def _window(uploader):
    """The browser tab the user would be looking at."""
    return uploader._context.pages[0]


def test_attaches_the_slides_in_order_and_fills_in_the_post(tmp_path, site):
    uploader = _uploader(tmp_path, site)
    try:
        report = _upload(uploader, _slides(tmp_path), debug=True)
        window = _window(uploader)
        assert window.locator("#files li").all_inner_texts() == ["01.png", "02.png", "03.png"]
        # The prefilled "IMG_0001" and "01.png" are replaced; one description line per Enter.
        assert window.locator(".titleInput-x1").input_value() == TITLE
        box = window.locator(".caption-editor [contenteditable]")
        lines = box.evaluate("box => Array.from(box.childNodes, line => line.textContent)")
        # Each hashtag is picked from the list (not the longer one above it); TikTok's space
        # after a picked hashtag replaces the typed one.
        assert [line.rstrip() for line in lines] == DESCRIPTION.split("\n")
        # No "posted": Post is the user's click.
        body = window.evaluate("({...document.body.dataset})")
        assert body == {"hashtags": "#manhwa #webtoon", "sound": "solo leveling 1"}
    finally:
        uploader.close()
    assert report == UploadReport(
        attached=True,
        captioned=True,
        problems=[],
        titled=True,
        sound="solo leveling 1 (00:31 · Fixture)",
    )
    assert (tmp_path / "browser" / "reads").is_dir()
    assert not (tmp_path / "debug").exists()  # nothing was missing


def test_hashtags_tiktok_doesnt_suggest_stay_plain_text(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?no-hashtags", hashtag_timeout=0.3)
    try:
        report = _upload(uploader, _slides(tmp_path), sound=None)
        body = _window(uploader).evaluate("({...document.body.dataset})")
        box = _window(uploader).locator(".caption-editor [contenteditable]")
        assert box.inner_text().split("\n")[-1] == "#manhwa #webtoon"
    finally:
        uploader.close()
    assert body == {"escaped": "yes"}  # the list was closed, nothing picked, no sound
    assert (report.captioned, report.problems, report.sound) == (True, [], None)


def test_missing_title_box_and_sound_are_problems(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?no-title&no-sounds", sound_timeout=0.5)
    try:
        report = _upload(uploader, _slides(tmp_path), sound="nothing like this")
    finally:
        uploader.close()
    assert (report.titled, report.captioned, report.sound) == (False, True, None)
    assert report.problems == [
        "title box not found — type the title yourself",
        'no sound found for "nothing like this" — add one yourself',
    ]


def test_a_missing_caption_box_is_a_problem_not_a_crash(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?no-caption")
    try:
        report = _upload(uploader, _slides(tmp_path), debug=False)
    finally:
        uploader.close()
    assert report == UploadReport(
        attached=True,
        captioned=False,
        problems=["description box not found — paste it from caption.txt yourself"],
        titled=True,
        sound="solo leveling 1 (00:31 · Fixture)",
    )


def test_an_editor_that_never_opens_is_a_problem(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?no-editor")
    try:
        report = _upload(uploader, _slides(tmp_path), debug=False)
    finally:
        uploader.close()
    assert report.attached is True
    assert report.problems == [
        "the post editor didn't open — check the browser window",
        "title box not found — type the title yourself",
        "description box not found — paste it from caption.txt yourself",
        "Add sound button not found — add one yourself",
    ]


def test_a_page_without_a_file_input_is_a_problem(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?no-input", page_timeout=0.5)
    try:
        report = _upload(uploader, _slides(tmp_path), debug=False)
    finally:
        uploader.close()
    assert report == UploadReport(
        attached=False,
        captioned=False,
        problems=[
            "upload button not found — drag the slides in yourself",
            "title and description not typed — paste caption.txt yourself",
        ],
    )


def test_not_logged_in_says_how_to_log_in_and_closes_the_browser(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?needs-session")
    try:
        with pytest.raises(NotLoggedIn) as e:
            _upload(uploader, _slides(tmp_path), debug=False)
        assert uploader._context is None  # already closed
    finally:
        uploader.close()
    assert str(e.value) == "@reads is not logged in — run: manhwatok login @reads"


# login() waits for the user to quit Chrome; this "user" quits a headless one a few seconds in.
USER_QUITS_CHROME = """
import signal, subprocess, sys
chrome = subprocess.Popen([sys.argv[1], "--headless=new", *sys.argv[2:]])
try:
    chrome.wait(5)
except subprocess.TimeoutExpired:
    chrome.send_signal(signal.SIGTERM)
    chrome.wait(20)
"""


def test_a_login_in_chrome_is_used_by_the_upload(tmp_path, site):
    chrome = _find_chrome()
    if chrome is None:
        pytest.skip("needs Google Chrome")
    options = {"chrome": [sys.executable, "-c", USER_QUITS_CHROME, chrome]}
    _uploader(tmp_path, site, options=options).login("reads")

    uploader = _uploader(
        tmp_path, site, "fake_upload.html?needs-session", options={"channel": "chrome"}
    )
    try:
        report = _upload(uploader, _slides(tmp_path), debug=False)
        assert (report.attached, report.captioned) == (True, True)
        with pytest.raises(NotLoggedIn):  # another account: its own profile, never logged in
            _upload(uploader, _slides(tmp_path / "other"), handle="other")
    finally:
        uploader.close()


def test_debug_saves_a_screenshot_and_the_page_when_something_is_missing(tmp_path, site):
    uploader = _uploader(tmp_path, site, "fake_upload.html?no-caption")
    try:
        report = _upload(uploader, _slides(tmp_path), debug=True)
    finally:
        uploader.close()
    [folder] = (tmp_path / "debug").iterdir()
    assert report.debug_dir == folder
    assert re.fullmatch(r"20260914-a3f9-\d{8}-\d{6}", folder.name)  # <post id>-<local time>
    assert (folder / "screenshot.png").read_bytes().startswith(b"\x89PNG")
    assert 'data-e2e="post_video_button"' in (folder / "page.html").read_text()
