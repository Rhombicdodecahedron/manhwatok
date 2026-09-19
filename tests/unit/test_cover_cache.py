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


def test_cached_returns_none_without_downloading(tmp_path):
    cache = _cache(tmp_path, Cdn())
    m = manhwa(anilist_id=136220, cover_url=URL)
    assert cache.cached(m) is None
    assert not (tmp_path / "covers").exists()


def test_cached_returns_path_after_download(tmp_path):
    cache = _cache(tmp_path, Cdn())
    m = manhwa(anilist_id=136220, cover_url=URL)
    downloaded = cache.get(m)
    assert cache.cached(m) == downloaded


def test_cached_is_none_for_missing_cover_url(tmp_path):
    assert _cache(tmp_path, Cdn()).cached(manhwa(cover_url="")) is None


# --- banners (Phase 5 art) -----------------------------------------------------------------

BANNER = "https://s4.anilist.co/file/anilistcdn/media/manga/banner/136220-abc.jpg"


def test_banner_downloads_once_and_is_kept_beside_the_cover(tmp_path):
    cdn = Cdn()
    cache = _cache(tmp_path, cdn)
    m = manhwa(anilist_id=136220, cover_url=URL, banner_url=BANNER)
    first = cache.get_banner(m)
    second = cache.get_banner(m)
    assert first == second == tmp_path / "covers" / "136220-banner.jpg"
    assert first.read_bytes() == b"\x89PNG fake"
    assert len(cdn.requests) == 1
    assert cache.get(m) == tmp_path / "covers" / "136220.png"  # cover is a separate file


def test_cached_banner_never_downloads(tmp_path):
    cdn = Cdn()
    m = manhwa(anilist_id=7, banner_url=BANNER)
    assert _cache(tmp_path, cdn).cached_banner(m) is None
    assert cdn.requests == []


def test_missing_banner_url(tmp_path):
    with pytest.raises(MetadataError, match="no banner image"):
        _cache(tmp_path, Cdn()).get_banner(manhwa(banner_url=""))


def test_banner_http_error_raises(tmp_path):
    with pytest.raises(MetadataError, match="banner download failed for Doom Breaker"):
        _cache(tmp_path, Cdn(status=500)).get_banner(
            manhwa(title="Doom Breaker", banner_url=BANNER)
        )


CHARACTER = "https://s4.anilist.co/file/anilistcdn/character/large/b129928-abc.png"


def test_character_image_is_kept_beside_the_cover_and_banner(tmp_path):
    cdn = Cdn()
    cache = _cache(tmp_path, cdn)
    m = manhwa(anilist_id=136220, cover_url=URL, banner_url=BANNER, character_url=CHARACTER)
    first = cache.get_character(m)
    assert first == tmp_path / "covers" / "136220-char.png"
    assert cache.get_character(m) == first and len(cdn.requests) == 1
    assert {p.name for p in (tmp_path / "covers").iterdir()} == {"136220-char.png"}


def test_cached_character_never_downloads(tmp_path):
    cdn = Cdn()
    assert _cache(tmp_path, cdn).cached_character(manhwa(character_url=CHARACTER)) is None
    assert cdn.requests == []


def test_missing_character_url(tmp_path):
    with pytest.raises(MetadataError, match="no character image"):
        _cache(tmp_path, Cdn()).get_character(manhwa(character_url=""))


def test_character_http_error_raises(tmp_path):
    with pytest.raises(MetadataError, match="character download failed for Doom Breaker"):
        _cache(tmp_path, Cdn(status=503)).get_character(
            manhwa(title="Doom Breaker", character_url=CHARACTER)
        )


def test_further_characters_are_kept_numbered(tmp_path):
    cdn = Cdn()
    cache = _cache(tmp_path, cdn)
    urls = [CHARACTER, CHARACTER.replace("abc", "def"), CHARACTER.replace("abc", "ghi")]
    m = manhwa(anilist_id=136220, character_url=urls[0], character_urls=urls)
    assert cache.get_character(m, 0) == tmp_path / "covers" / "136220-char.png"
    assert cache.get_character(m, 2) == tmp_path / "covers" / "136220-char3.png"
    assert cache.cached_character(m, 2) == tmp_path / "covers" / "136220-char3.png"
    assert cache.cached_character(m, 1) is None


def test_a_character_past_the_last_one_is_missing(tmp_path):
    m = manhwa(character_url=CHARACTER, character_urls=[CHARACTER])
    with pytest.raises(MetadataError, match="no character image"):
        _cache(tmp_path, Cdn()).get_character(m, 1)
    assert _cache(tmp_path, Cdn()).cached_character(m, 1) is None


def test_an_old_title_with_one_character_still_has_it(tmp_path):
    m = manhwa(anilist_id=5, character_url=CHARACTER)  # saved before character_urls existed
    assert _cache(tmp_path, Cdn()).get_character(m, 0).name == "5-char.png"
