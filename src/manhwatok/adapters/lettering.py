"""Where the lettering is on a stretch of a chapter: every line of a speech bubble, a thought, a
caption or a system window, however it is drawn.

Bubbles are also found by their shape (`panel_cutter.bubble_rows`), but a bubble on the page's
own margin with a thin or broken outline has no shape to find. Its lettering always shows, so
RapidOCR's text detector (no recognition: finding is enough, ~0.25s a slide) marks the rows a
cut through the art must stay clear of.
"""

from __future__ import annotations

from functools import cache
from typing import Any, Callable

import numpy as np
from PIL import Image

# RapidOCR's call: (image, use_det=, use_cls=, use_rec=) -> ([box, ...] | None, elapsed)
Engine = Callable[..., tuple[Any, Any]]


@cache
def rapid_ocr() -> Engine:
    """One RapidOCR model for the whole run, loaded on first use."""
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


class Lettering:
    """`find(img)` -> the (top, bottom) rows of each line of lettering on it."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    def __call__(self, img: Image.Image) -> list[tuple[int, int]]:
        engine = self._engine or rapid_ocr()
        boxes, _ = engine(
            np.asarray(img.convert("RGB")), use_det=True, use_cls=False, use_rec=False
        )
        return [
            (int(min(point[1] for point in box)), int(max(point[1] for point in box)))
            for box in boxes or []
        ]
