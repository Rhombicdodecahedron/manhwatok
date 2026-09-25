"""Where to cut a webtoon strip into slides, without cutting through the art.

A webtoon chapter is one tall strip. To post it, it has to be cut into slide-sized pieces — and
a cut through a face or a speech bubble is worse than a short slide. What separates panels is a
gutter: a run of rows that are all one colour. So the strip is measured one row at a time (how
far apart the lightest and darkest samples in that row are) and cut in the gutter lowest down
within reach of a full slide — reaching as far as half a slide up for one, since a short slide
padded with margin is better than a sliced bubble. With no gutter in reach, the slide is kept
full and cut through the art like a crop, raised only to clear a bubble. Nothing here sees a pixel: the adapter measures
(and says which rows hold a bubble or lettering), this decides.

Webtoons also pace a scene with long empty stretches, which on a slideshow are just blank
slides: `squeeze` shortens them, and `is_blank` says a piece has nothing on it at all.
"""

from __future__ import annotations

from typing import Sequence

SLIDE_W, SLIDE_H = 1080, 1920
GUTTER_FLATNESS = 6.0  # 0-255 spread under which a row is a gutter rather than drawing
CUT_SLACK = 1020  # how far above a full slide a gutter is still worth cutting at
MIN_PIECE = 480  # never cut so close above that a sliver is left behind
MIN_GUTTER = 24  # rows a flat run needs to be a gutter; thinner is the gap between two lines
MAX_GAP = 200  # rows an empty stretch is squeezed down to
BLANK_SHARE = 0.97  # share of flat rows at which a piece has nothing on it


def gutter_bands(
    spreads: Sequence[float],
    flatness: float = GUTTER_FLATNESS,
    protected: Sequence[bool] | None = None,
) -> list[tuple[int, int]]:
    """Half-open runs of rows flat enough to cut through. A protected row (inside a bubble)
    never is, however flat."""
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for row, spread in enumerate(spreads):
        if spread < flatness and not (protected and protected[row]):
            start = row if start is None else start
        elif start is not None:
            bands.append((start, row))
            start = None
    if start is not None:
        bands.append((start, len(spreads)))
    return bands


def gutter_cut(
    spreads: Sequence[float],
    target: int = SLIDE_H,
    slack: int = CUT_SLACK,
    min_piece: int = MIN_PIECE,
    flatness: float = GUTTER_FLATNESS,
    min_gutter: int = MIN_GUTTER,
    protected: Sequence[bool] | None = None,
) -> int | None:
    """The middle of the lowest gutter (at least `min_gutter` rows, none of them `protected`)
    reaching into [target - slack, target], or None when there is none."""
    floor = max(min_piece, target - slack)
    reachable = [
        (min(end, target), max(start, floor))
        for start, end in gutter_bands(spreads, flatness, protected)
        if end - start >= min_gutter and end > floor and start < target
    ]
    if not reachable:
        return None
    end, start = max(reachable)
    if end >= target:
        return target  # the slide's own edge is gutter: take the whole slide
    return (start + end) // 2


def art_cut(
    spreads: Sequence[float],
    target: int = SLIDE_H,
    slack: int = CUT_SLACK,
    min_piece: int = MIN_PIECE,
    protected: Sequence[bool] | None = None,
) -> int:
    """Where to cut through the art when there is no gutter: a full slide, like any crop, raised
    only as far as it takes to clear what is `protected` (a bubble, lettering) — never a short
    slide padded out to hide the cut. `target` when everything in reach is protected."""
    floor = max(min_piece, target - slack)
    for row in range(min(target, len(spreads)), floor - 1, -1):
        if row == len(spreads) or not (protected and protected[row]):
            return row
    return target


def next_cut(
    spreads: Sequence[float],
    target: int = SLIDE_H,
    slack: int = CUT_SLACK,
    min_piece: int = MIN_PIECE,
    flatness: float = GUTTER_FLATNESS,
    min_gutter: int = MIN_GUTTER,
    protected: Sequence[bool] | None = None,
) -> int | None:
    """Where to cut a strip whose first `len(spreads)` rows are known, so that the piece above
    the cut is at most `target` tall: in a gutter (`gutter_cut`), else through the art
    (`art_cut`). None while the strip is shorter than a slide: more of it may still arrive."""
    if len(spreads) < target:
        return None
    cut = gutter_cut(spreads, target, slack, min_piece, flatness, min_gutter, protected)
    return cut if cut is not None else art_cut(spreads, target, slack, min_piece, protected)


def cut_rows(
    spreads: Sequence[float],
    target: int = SLIDE_H,
    slack: int = CUT_SLACK,
    min_piece: int = MIN_PIECE,
    flatness: float = GUTTER_FLATNESS,
    min_gutter: int = MIN_GUTTER,
    protected: Sequence[bool] | None = None,
) -> list[int]:
    """Every row a whole strip is cut at, ascending. What is left under the last cut is the
    last piece, however short."""
    rows: list[int] = []
    at = 0
    while True:
        cut = next_cut(
            spreads[at:],
            target,
            slack,
            min_piece,
            flatness,
            min_gutter,
            protected[at:] if protected else None,
        )
        if cut is None:
            return rows
        at += cut
        rows.append(at)


def squeeze(
    spreads: Sequence[float],
    max_gap: int = MAX_GAP,
    flatness: float = GUTTER_FLATNESS,
    ended: bool = False,
) -> list[tuple[int, int]]:
    """The half-open row ranges to keep so that no empty stretch is longer than `max_gap`: the
    top and bottom of a long one are kept, its middle dropped. A stretch running off the bottom
    may go on in the next page, so it is left whole until the strip has `ended`."""
    kept: list[tuple[int, int]] = []
    at = 0
    for start, end in gutter_bands(spreads, flatness):
        if end - start <= max_gap or (end == len(spreads) and not ended):
            continue
        top = start + max_gap // 2
        kept.append((at, top))
        at = end - (max_gap - max_gap // 2)
    kept.append((at, len(spreads)))
    return kept


def is_blank(
    spreads: Sequence[float], flatness: float = GUTTER_FLATNESS, share: float = BLANK_SHARE
) -> bool:
    """Whether a piece is (nearly) all margin: nothing worth a slide."""
    if not spreads:
        return False
    return sum(spread < flatness for spread in spreads) >= share * len(spreads)
