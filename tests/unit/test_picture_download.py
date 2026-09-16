import httpx
import pytest

from manhwatok.adapters.picture_download import MAX_BYTES, download_picture, looks_like_url
from manhwatok.domain.errors import ManhwatokError


class Host:
    def __init__(self, status=200, body=b"\x89PNG pretend", content_type="image/png"):
        self.status, self.body, self.content_type = status, body, content_type
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        headers = {"Content-Type": self.content_type} if self.content_type else {}
        return httpx.Response(self.status, content=self.body, headers=headers)


def _get(url, host, tmp_path):
    return download_picture(
        url, tmp_path, client=httpx.Client(transport=httpx.MockTransport(host))
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://example.test/a.png", True),
        ("http://example.test/a.png", True),
        ("~/Downloads/pick.png", False),
        ("/abs/path.png", False),
        ("pick.png", False),
        ("C:\\pics\\a.png", False),
    ],
)
def test_looks_like_url(text, expected):
    assert looks_like_url(text) is expected


def test_downloads_to_a_file_named_by_its_type(tmp_path):
    host = Host()
    path = _get("https://example.test/art", host, tmp_path)
    assert path.suffix == ".png"
    assert path.read_bytes() == b"\x89PNG pretend"
    assert host.requests[0].headers["User-Agent"] == "manhwatok/0.1"


def test_keeps_the_extension_from_the_url_when_it_has_one(tmp_path):
    path = _get("https://example.test/art/cool.jpg", Host(content_type="image/jpeg"), tmp_path)
    assert path.suffix == ".jpg"


def test_url_query_string_is_not_mistaken_for_an_extension(tmp_path):
    path = _get("https://example.test/a.png?w=1200&sig=xyz", Host(), tmp_path)
    assert path.suffix == ".png"


def test_rejects_a_page_that_is_not_a_picture(tmp_path):
    """Pasting the gallery page rather than the image is the easy mistake to make."""
    host = Host(body=b"<html>gallery</html>", content_type="text/html; charset=utf-8")
    with pytest.raises(ManhwatokError, match="not a picture"):
        _get("https://example.test/gallery", host, tmp_path)


def test_rejects_an_http_error(tmp_path):
    with pytest.raises(ManhwatokError, match="HTTP 404"):
        _get("https://example.test/gone.png", Host(status=404), tmp_path)


def test_rejects_an_empty_body(tmp_path):
    with pytest.raises(ManhwatokError, match="empty"):
        _get("https://example.test/a.png", Host(body=b""), tmp_path)


def test_rejects_something_far_too_big(tmp_path):
    host = Host(body=b"x" * (MAX_BYTES + 1))
    with pytest.raises(ManhwatokError, match="too big"):
        _get("https://example.test/huge.png", host, tmp_path)


def test_reports_a_network_failure(tmp_path):
    def down(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(ManhwatokError, match="could not download"):
        _get("https://example.test/a.png", down, tmp_path)


def test_rejects_an_unsupported_image_type(tmp_path):
    host = Host(body=b"<svg/>", content_type="image/svg+xml")
    with pytest.raises(ManhwatokError, match="not a picture"):
        _get("https://example.test/a.svg", host, tmp_path)
