"""Bundled OFL fonts: Anton for display text, Inter (variable) for body text."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from PIL import ImageFont

_DIR = files("manhwatok") / "assets" / "fonts"
SEMIBOLD = 600
EXTRABOLD = 800


@lru_cache(maxsize=None)
def anton(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_DIR / "Anton-Regular.ttf"), size)


@lru_cache(maxsize=None)
def inter(size: int, weight: int = SEMIBOLD) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(_DIR / "Inter-Variable.ttf"), size)
    font.set_variation_by_axes([32, weight])  # axes: optical size 14–32, weight 100–900
    return font


def inter_semibold(size: int) -> ImageFont.FreeTypeFont:
    return inter(size, SEMIBOLD)


def inter_extrabold(size: int) -> ImageFont.FreeTypeFont:
    return inter(size, EXTRABOLD)
