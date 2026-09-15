import pytest

from manhwatok.domain.color import (
    MIN_LUMINANCE,
    check_accent,
    hex_to_rgb,
    is_hex_color,
    luminance,
    readable_accent,
)
from manhwatok.domain.errors import InvalidName
from manhwatok.domain.post import DEFAULT_ACCENT


def test_bright_colour_is_kept_and_lowercased():
    assert readable_accent("#43C9E4") == "#43c9e4"


def test_dark_colour_is_lightened_until_readable():
    out = readable_accent("#6b1a1a")
    assert out != "#6b1a1a"
    assert luminance(hex_to_rgb(out)) >= MIN_LUMINANCE
    r, g, b = hex_to_rgb(out)
    assert r > g and r > b  # still reads as red


def test_dark_red_keeps_its_hue():
    assert readable_accent("#6b1a1a") == "#e28888"


def test_black_becomes_a_readable_grey():
    r, g, b = hex_to_rgb(readable_accent("#000000"))
    assert r == g == b
    assert luminance((r, g, b)) >= MIN_LUMINANCE


@pytest.mark.parametrize("bad", [None, "", "red", "#12345", "43c9e4", "#gggggg"])
def test_invalid_colour_falls_back_to_default(bad):
    assert readable_accent(bad) == DEFAULT_ACCENT


def test_custom_default():
    assert readable_accent(None, default="#ffffff") == "#ffffff"


def test_is_hex_color():
    assert is_hex_color("#43c9e4")
    assert not is_hex_color("43c9e4")
    assert not is_hex_color("#43c9e")


def test_check_accent_lowercases_or_raises():
    assert check_accent("#43C9E4") == "#43c9e4"
    with pytest.raises(InvalidName, match=r"^accent must look like #43c9e4, got 'cyan'$"):
        check_accent("cyan")


def test_luminance_extremes():
    assert luminance((0, 0, 0)) == 0
    assert luminance((255, 255, 255)) == pytest.approx(1.0)
