"""Painting out the website marks scanlators stamp into the art ("ASURASCANS.COM" on a badge).

A mark is found by what it says: RapidOCR reads the slide and a line that is a website address
is a mark. It usually sits on a badge (a banner in one flat colour, with the site's icon beside
it), so the patch grows from the words across the badge's own colour and a little beyond, for
the icon. OpenCV's inpainting (Telea) then fills it from the art around it, and grain matching
the surroundings is laid over the fill so it does not show as a smooth smear. Good on skies,
walls and gutters, where marks mostly sit; on detailed art the fill is plainly a guess.
"""

from __future__ import annotations

from typing import Any, Callable

import cv2
import numpy as np
from PIL import Image

from manhwatok.adapters.lettering import rapid_ocr
from manhwatok.adapters.panel_junk import MIN_SCORE, WEBSITE

BADGE_REACH = 4  # text heights around the words a badge may reach
BADGE_TOLERANCE = 60  # summed RGB difference from the badge's colour still counted as badge
INPAINT_RADIUS = 9
READ_SCALE = 2  # marks are read on a copy this many times smaller: as sure, and faster
GRAIN_RING = 12  # pixels around the patch whose grain it copies

# RapidOCR's call: (image, use_cls=...) -> ([(box, text, score), ...] | None, elapsed)
Engine = Callable[..., tuple[Any, Any]]
Box = tuple[int, int, int, int]  # left, top, right, bottom


class Watermarks:
    """`clean(img)` -> the picture with its website marks painted out, or None when it has
    none. The OCR model loads on first use."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    def __call__(self, img: Image.Image) -> Image.Image | None:
        rgb = img.convert("RGB")
        small = rgb.resize(
            (max(1, rgb.width // READ_SCALE), max(1, rgb.height // READ_SCALE)),
            Image.Resampling.LANCZOS,
        )
        found, _ = (self._engine or rapid_ocr())(np.asarray(small), use_cls=False)
        pixels = np.asarray(rgb)
        marks = [
            _badge(pixels, _bounds(box, READ_SCALE))
            for box, text, score in found or []
            if score >= MIN_SCORE and WEBSITE.search(text)
        ]
        if not marks:
            return None
        return Image.fromarray(paint_out(pixels, marks))


def _bounds(box, scale: int = 1) -> Box:
    xs, ys = [p[0] * scale for p in box], [p[1] * scale for p in box]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


def _badge(pixels: np.ndarray, words: Box) -> Box:
    """What to paint out for words at `words`: the badge they sit on (the run of their commonest
    colour around them), padded by its height sideways for the icon; or the words themselves,
    padded, when they are laid straight over the art."""
    height, width = pixels.shape[:2]
    left, top, right, bottom = words
    line = max(1, bottom - top)
    under = pixels[top:bottom, left:right].reshape(-1, 3) // 8 * 8
    if not under.size:
        return words
    colours, counts = np.unique(under, axis=0, return_counts=True)
    colour = colours[counts.argmax()].astype(int) + 4
    wl, wt = max(0, left - BADGE_REACH * line), max(0, top - BADGE_REACH * line // 2)
    wr, wb = min(width, right + BADGE_REACH * line), min(height, bottom + BADGE_REACH * line // 2)
    near = (np.abs(pixels[wt:wb, wl:wr].astype(int) - colour).sum(axis=2) <= BADGE_TOLERANCE)
    near = near.astype(np.uint8)
    near[top - wt : bottom - wt, left - wl : right - wl] = 1
    _, labels, stats, _ = cv2.connectedComponentsWithStats(near, connectivity=8)
    x, y, w, h, _ = stats[labels[(top + bottom) // 2 - wt, (left + right) // 2 - wl]]
    if x == 0 or y == 0 or x + w >= wr - wl or y + h >= wb - wt:  # ran on: no badge, just words
        pad = max(4, line // 2)
        return max(0, left - pad), max(0, top - pad), min(width, right + pad), min(height, bottom + pad)
    side, edge = h, max(4, h // 4)
    return (
        max(0, wl + x - side),
        max(0, wt + y - edge),
        min(width, wl + x + w + edge),
        min(height, wt + y + h + edge),
    )


def paint_out(pixels: np.ndarray, boxes: list[Box]) -> np.ndarray:
    """RGB `pixels` with `boxes` filled in from around them, grain and all."""
    mask = np.zeros(pixels.shape[:2], np.uint8)
    for left, top, right, bottom in boxes:
        mask[top:bottom, left:right] = 255
    filled = cv2.cvtColor(
        cv2.inpaint(cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR), mask, INPAINT_RADIUS, cv2.INPAINT_TELEA),
        cv2.COLOR_BGR2RGB,
    )
    ring = cv2.dilate(mask, np.ones((GRAIN_RING * 2 + 1,) * 2, np.uint8)) > 0
    ring &= mask == 0
    if ring.any():
        smooth = cv2.GaussianBlur(pixels, (0, 0), 2).astype(np.float32)
        grain = float((pixels.astype(np.float32) - smooth)[ring].std())
        noise = np.random.default_rng(0).normal(0, grain, pixels.shape[:2])[..., None]
        grained = np.clip(filled.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        filled = np.where((mask > 0)[..., None], grained, filled)
    return filled
