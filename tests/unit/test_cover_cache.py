import httpx
import pytest

from manhwatok.adapters.cover_cache import CoverCache
from manhwatok.domain.errors import MetadataError
from tests.unit.fakes import manhwa

URL = "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/bx136220-u9sewv3u02mN.png"


class Cdn:
    def __init__(self, status=200, body=b"\x89PNG fake"):
        self.status, self.body, self.requests = status, body, []

    def __call__(self, request):
        self.requests.append(request)
        return httpx.Response(self.status, content=self.body)


def _cache(tmp_path, cdn):
    return CoverCache(tmp_path / "covers", client=httpx.Client(transport=httpx.MockTransport(cdn)))


def test_downloads_once_then_serves_from_disk(tmp_path):
    cdn = Cdn()
    cache = _cache(tmp_path, cdn)
    m = manhwa(anilist_id=136220, cover_url=URL)
    first = cache.get(m)
    second = cache.get(m)
    assert first == second == tmp_path / "covers" / "136220.png"
    assert first.read_bytes() == b"\x89PNG fake"
    assert len(cdn.requests) == 1
    assert cdn.requests[0].headers["User-Agent"] == "manhwatok/0.1"
    assert not list((tmp_path / "covers").glob("*.part"))


def test_unknown_extension_saved_as_jpg(tmp_path):
    path = _cache(tmp_path, Cdn()).get(manhwa(anilist_id=5, cover_url="https://x.test/cover"))
    assert path.name == "5.jpg"


def test_http_error_raises_and_writes_nothing(tmp_path):
    with pytest.raises(MetadataError, match="HTTP 404"):
        _cache(tmp_path, Cdn(status=404)).get(manhwa(title="Doom Breaker", cover_url=URL))
    assert not (tmp_path / "covers").exists() or not any((tmp_path / "covers").iterdir())


def test_network_error_raises(tmp_path):
    def down(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(MetadataError, match="cover download failed for Doom Breaker"):
        _cache(tmp_path, down).get(manhwa(title="Doom Breaker", cover_url=URL))


def test_missing_cover_url(tmp_path):
    with pytest.raises(MetadataError, match="no cover image"):
        _cache(tmp_path, Cdn()).get(manhwa(cover_url=""))
