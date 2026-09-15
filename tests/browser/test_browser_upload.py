"""The real PlaywrightUploader in headless Chromium against the fixture pages in tests/fixtures,
served on 127.0.0.1 — never tiktok.com. Temporary profiles, no pauses, no typing delay.
Skipped unless the upload extra and its Chromium are installed:
    uv sync --extra upload && uv run playwright install chromium"""

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from manhwatok.adapters.playwright_uploader import PlaywrightUploader
from manhwatok.adapters.tiktok_page import TikTokPage
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


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def site():
    """tests/fixtures over http://127.0.0.1:<free port>."""
    handler = functools.partial(_QuietHandler, directory=str(FIXTURES))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join()


def _uploader(tmp_path, site, upload="fake_upload.html", **page_fields) -> PlaywrightUploader:
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
