"""Bundled OFL font: Montserrat (variable, one axis: weight 100–900) for all slide text."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from PIL import ImageFont

_DIR = files("manhwatok") / "assets" / "fonts"
BLACK = 900
EXTRABOLD = 800
SEMIBOLD = 600


@lru_cache(maxsize=None)
def montserrat(size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(_DIR / "Montserrat-Variable.ttf"), size)
    font.set_variation_by_axes([weight])
    return font


def display(size: int) -> ImageFont.FreeTypeFont:
    """Titles, names, rank numbers (drawn uppercase)."""
    return montserrat(size, BLACK)


def bold(size: int) -> ImageFont.FreeTypeFont:
    """Pills and the follow line."""
    return montserrat(size, EXTRABOLD)


def body(size: int) -> ImageFont.FreeTypeFont:
    """Hooks and the end-slide recap list."""
    return montserrat(size, SEMIBOLD)
