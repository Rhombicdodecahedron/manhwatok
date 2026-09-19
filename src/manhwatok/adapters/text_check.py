"""Whether a picture has words on it: speech bubbles, meme captions, posters, tweets.

A pin's caption says nothing about what is drawn on it, so the picture itself is read with
RapidOCR (the `pinterest` extra), offline. Detection alone is no use here — on detailed art it
boxes hair and fabric as "text" — so a word only counts once it is also recognised with
confidence. Checked by hand against 80 of Pinterest's most-liked pins for four titles: every
bubble, caption, tweet, poster and collage was caught, and no clean picture was, with artists'
@handles and small corner logos let through. Korean sound effects drawn into the art mostly
read as nothing and pass; they are part of a panel, not a bubble over it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError

MIN_SCORE = 0.8  # recognition confidence a word needs to count
BIG_WORD = 10.0  # % of the picture: a word this big counts even when read with less confidence
BIG_SCORE = 0.5
MAX_TEXT = 0.5  # % of the picture that confident words may cover before it "has text"

# RapidOCR's call: (image path, use_cls=...) -> ([(box, text, score), ...] | None, elapsed)
Engine = Callable[..., tuple[Any, Any]]


def covers_text(found: list, width: int, height: int) -> bool:
    """Whether OCR results `found` on a width x height picture amount to words on it."""
    covered = 0.0
    for box, text, score in found:
        if sum(c.isalnum() for c in text) < 2 or text.strip().startswith("@"):
            continue  # a stray mark in the art, or the artist's handle
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        area = 100 * (max(xs) - min(xs)) * (max(ys) - min(ys)) / (width * height)
        if score >= MIN_SCORE or (area >= BIG_WORD and score >= BIG_SCORE):
            covered += area
    return covered >= MAX_TEXT


class TextCheck:
    """`check(path)` -> True when the picture has words on it. The OCR model loads on first use."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    def __call__(self, path: Path) -> bool:
        try:
            with Image.open(path) as img:
                width, height = img.size
        except (OSError, UnidentifiedImageError):
            return False  # nothing to read; whoever opens it next will find out
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        found, _ = self._engine(str(path), use_cls=False)
        return covers_text(found or [], width, height)


def build_text_check() -> TextCheck | None:
    """A text check when RapidOCR is installed, else None (pictures are then not read)."""
    if importlib.util.find_spec("rapidocr_onnxruntime") is None:
        return None
    return TextCheck()
