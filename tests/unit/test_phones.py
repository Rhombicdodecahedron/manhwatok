import pytest

from manhwatok.adapters import phones
from manhwatok.domain.errors import ManhwatokError, UploadUnavailable

DEVICES = """List of devices attached
R5CY10GLA9E            device usb:5-1 product:b6qxeea model:SM_F741B device:b6q transport_id:2
emulator-5554          offline transport_id:3
0123456789ABCDEF       unauthorized usb:1-4 transport_id:4

"""


def test_phones_are_listed_with_their_state_and_model():
    seen = []

    def run(argv):
        seen.append(argv[-2:])
        return DEVICES

    found = phones.list_phones(run)
    assert seen == [["devices", "-l"]]
    assert [(p.serial, p.state, p.model, p.ready) for p in found] == [
        ("R5CY10GLA9E", "device", "SM F741B", True),
        ("emulator-5554", "offline", "", False),
        ("0123456789ABCDEF", "unauthorized", "", False),
    ]
    assert found[2].problem == "needs you to allow USB debugging on the phone"
    assert found[1].problem == "is offline — unplug it and plug it back in"
    assert found[0].problem == ""


def test_no_adb_says_how_to_get_it(monkeypatch):
    monkeypatch.setattr(phones, "_find_adb", lambda: None)
    with pytest.raises(UploadUnavailable) as e:
        phones.list_phones()
    assert "adb" in str(e.value)


def test_whether_tiktok_is_installed():
    def run(argv):
        assert argv == ["adb", "-s", "R5CY", "shell", "pm", "list", "packages",
                        "com.zhiliaoapp.musically"]
        return "package:com.zhiliaoapp.musically\n"

    assert phones.has_app("R5CY", "com.zhiliaoapp.musically", run)
    assert not phones.has_app("R5CY", "com.ss.android.ugc.trill", lambda argv: "")


def test_a_screen_is_a_png():
    png = b"\x89PNG\r\n\x1a\n" + b"rest"
    assert phones.screencap("R5CY", lambda argv: png) == png
    with pytest.raises(ManhwatokError) as e:
        phones.screencap("R5CY", lambda argv: b"error: device offline")
    assert "could not see the screen of R5CY" in str(e.value)


@pytest.mark.parametrize("bad", ["", "a b", "x;rm", "../x", "$(id)"])
def test_serials_are_checked_before_they_reach_adb(bad):
    with pytest.raises(ManhwatokError):
        phones.check_serial(bad)


def test_a_warning_before_the_picture_is_skipped():
    """A phone with two screens (a flip's cover screen) warns before the picture."""
    png = b"\x89PNG\r\n\x1a\n" + b"rest"
    said = b"[Warning] Multiple displays were found, but no display id was specified!\n" + png
    assert phones.screencap("R5CY", lambda argv: said) == png
