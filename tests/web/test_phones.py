import pytest

pytest.importorskip("fastapi")

from manhwatok.adapters.phones import Phone  # noqa: E402
from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.errors import ManhwatokError, UploadUnavailable  # noqa: E402
from manhwatok.web.phones import Phones  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\nframe"


def _phones(listed=None, error=None, screens=None):
    grabs = []

    def list_fn():
        if error:
            raise error
        return listed if listed is not None else [
            Phone("R5CY10GLA9E", "device", "SM F741B"), Phone("ABC", "unauthorized")]

    def screen_fn(serial):
        grabs.append(serial)
        if screens is not None and serial not in screens:
            raise ManhwatokError(f"could not see the screen of {serial}: offline")
        return PNG

    phones = Phones(list_fn=list_fn, screen_fn=screen_fn, app_fn=lambda s, p: True, cache_s=60)
    return phones, grabs


def test_the_page_lists_phones_their_state_and_their_accounts(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.store.accounts.add(Account(handle="reads", phone="R5CY10GLA9E"))
    ctx.store.accounts.add(Account(handle="loose"))
    phones, _ = _phones()
    with client_for(ctx, phones=phones) as client:
        html = client.get("/phones").text
    assert '<a href="/phones" aria-current="page"' in html
    assert "SM F741B" in html and "R5CY10GLA9E" in html
    assert 'data-live="/phones/R5CY10GLA9E/screen.png"' in html
    assert "needs you to allow USB debugging on the phone" in html
    assert 'data-live="/phones/ABC/screen.png"' not in html
    assert "@reads" in html and "@loose" in html  # the only ready phone takes the loose ones


def test_no_adb_or_no_phone_says_so(tmp_path):
    phones, _ = _phones(error=UploadUnavailable("phone upload needs adb (Android platform-tools)"))
    with client_for(make_ctx(tmp_path), phones=phones) as client:
        assert "phone upload needs adb" in client.get("/phones").text
    phones, _ = _phones(listed=[])
    with client_for(make_ctx(tmp_path), phones=phones) as client:
        assert "No phone plugged in" in client.get("/phones").text


def test_a_screen_is_served_fresh_and_grabbed_once_per_moment(tmp_path):
    phones, grabs = _phones()
    with client_for(make_ctx(tmp_path), phones=phones) as client:
        first = client.get("/phones/R5CY10GLA9E/screen.png")
        client.get("/phones/R5CY10GLA9E/screen.png")
    assert first.content == PNG and first.headers["content-type"] == "image/png"
    assert first.headers["cache-control"] == "no-store"
    assert grabs == ["R5CY10GLA9E"]  # the second came from the cache


def test_a_bad_serial_or_an_unseen_screen_is_a_404(tmp_path):
    phones, _ = _phones(screens={})
    with client_for(make_ctx(tmp_path), phones=phones) as client:
        assert client.get("/phones/R5CY10GLA9E/screen.png").status_code == 404
        assert client.get("/phones/a%3Bb/screen.png").status_code == 404


def test_an_uploader_is_built_for_the_mode_and_phone(tmp_path):
    ctx = make_ctx(tmp_path)
    built = []
    ctx.uploader_with = lambda settings: built.append(
        (settings.uploader, settings.auto_post, settings.phone)) or "uploader"
    assert ctx.uploader_for("phone-post", "R5CY") == "uploader"
    ctx.uploader_for("browser")
    assert built == [("phone", True, "R5CY"), ("browser", False, "")]
    assert ctx.settings.phone == "" and ctx.settings.uploader == "browser"  # untouched
