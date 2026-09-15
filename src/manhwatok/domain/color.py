"""Accent colours: keep AniList cover colours readable on the dark slide background."""

from __future__ import annotations

import colorsys
import re

from manhwatok.domain.errors import InvalidName
from manhwatok.domain.post import DEFAULT_ACCENT

MIN_LUMINANCE = 0.30
_HEX = re.compile(r"^#([0-9a-fA-F]{6})$")


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance, 0 (black) to 1 (white)."""
    r, g, b = (_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def is_hex_color(value: str) -> bool:
    return bool(_HEX.match(value))


def check_accent(accent: str) -> str:
    """A user-given accent as lowercase #rrggbb; raises InvalidName otherwise."""
    if not is_hex_color(accent):
        raise InvalidName(f"accent must look like #43c9e4, got {accent!r}")
    return accent.lower()


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    m = _HEX.match(color)
    if not m:
        raise ValueError(f"not a #rrggbb colour: {color!r}")
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{c:02x}" for c in rgb)


def readable_accent(color: str | None, default: str = DEFAULT_ACCENT) -> str:
    """Return `color` as lowercase #rrggbb, lightened (same hue and saturation) until its
    luminance reaches MIN_LUMINANCE so it stays readable on the dark slide background."""
    if not color or not _HEX.match(color):
        return default
    rgb = hex_to_rgb(color)
    h, lightness, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    while luminance(rgb) < MIN_LUMINANCE and lightness < 0.95:
        lightness = min(0.95, lightness + 0.05)
        rgb = tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, lightness, s))  # type: ignore[assignment]
    return _to_hex(rgb)
