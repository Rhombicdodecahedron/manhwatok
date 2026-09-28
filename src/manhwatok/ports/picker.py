from __future__ import annotations

from typing import NamedTuple, Protocol

from PIL import Image


class Focus(NamedTuple):
    """The part of one picture a cover should show: `images[index]`, cropped to `box`
    (left, top, right, bottom, in that picture's pixels)."""

    index: int
    box: tuple[int, int, int, int]


class PicturePicker(Protocol):
    def focus(self, images: list[Image.Image], count: int = 1) -> list[Focus]:
        """Up to `count` of the most striking parts of `images`, best first and not repeating
        each other: single drawn panels, or the best windows of tall ones, rather than whole
        pages with their gutters and speech bubbles. Empty when there are no images."""
        ...
