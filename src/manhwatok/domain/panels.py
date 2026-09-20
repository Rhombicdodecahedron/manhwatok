"""Where to cut a webtoon strip into slides, without cutting through the art.

A webtoon chapter is one tall strip. To post it, it has to be cut into slide-sized pieces — and
a cut through a face or a speech bubble is worse than a short slide. What separates panels is a
gutter: a run of rows that are all one colour. So the strip is measured one row at a time (how
far apart the lightest and darkest samples in that row are) and cut in the middle of a gutter
near a full slide. Nothing here sees a pixel: the adapter measures, this decides.
"""

from __future__ import annotations

from typing import Sequence

SLIDE_W, SLIDE_H = 1080, 1920
GUTTER_FLATNESS = 6.0  # 0-255 spread under which a row is a gutter rather than drawing
CUT_SLACK = 420  # how far above a full slide a gutter is still worth cutting at
MIN_PIECE = 480  # never cut so close above that a sliver is left behind


def gutter_bands(
    spreads: Sequence[float], flatness: float = GUTTER_FLATNESS
) -> list[tuple[int, int]]:
    """Half-open runs of rows flat enough to cut through."""
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for row, spread in enumerate(spreads):
        if spread < flatness:
            start = row if start is None else start
        elif start is not None:
            bands.append((start, row))
            start = None
    if start is not None:
        bands.append((start, len(spreads)))
    return bands


def next_cut(
    spreads: Sequence[float],
    target: int = SLIDE_H,
    slack: int = CUT_SLACK,
    min_piece: int = MIN_PIECE,
    flatness: float = GUTTER_FLATNESS,
) -> int | None:
    """Where to cut a strip whose first `len(spreads)` rows are known, so that the piece above
    the cut is at most `target` tall. The middle of the widest gutter reaching into
    [target - slack, target], else `target` itself — a full-bleed page has nowhere safe, and a
    hard cut beats a slide four times too tall. None while the strip is shorter than a slide:
    more of it may still arrive."""
    if len(spreads) < target:
        return None
    floor = max(min_piece, target - slack)
    reachable = [
        (min(end, target) - max(start, floor), max(start, floor), min(end, target))
        for start, end in gutter_bands(spreads[:target], flatness)
        if end > floor and start < target
    ]
    if not reachable:
        return target
    width, start, end = max(reachable)
    if end >= target:
        return target  # the slide's own edge is gutter: take the whole slide
    return (start + end) // 2 if width > 1 else start


def cut_rows(
    spreads: Sequence[float],
    target: int = SLIDE_H,
    slack: int = CUT_SLACK,
    min_piece: int = MIN_PIECE,
    flatness: float = GUTTER_FLATNESS,
) -> list[int]:
    """Every row a whole strip is cut at, ascending. What is left under the last cut is the
    last piece, however short."""
    rows: list[int] = []
    at = 0
    while True:
        cut = next_cut(spreads[at:], target, slack, min_piece, flatness)
        if cut is None:
            return rows
        at += cut
        rows.append(at)
