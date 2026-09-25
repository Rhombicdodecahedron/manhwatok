"""Cuts a chapter's pages into slides.

A webtoon chapter is one tall strip, delivered as pages that are themselves arbitrary slices of
it — a page boundary means nothing, and a panel often straddles two. So the pages are joined in
reading order, scaled to the slide's width, and cut wherever `domain.panels` says it is safe:
in a gutter, never through a bubble.

The strip is never held whole. A chapter at 1080 wide is around 100 000 rows, so pages are
added to a carry image and pieces are written off the top of it as soon as they are complete —
once enough of the strip below is known to see a bubble that straddles the slide's edge whole.
What each row holds is measured on a 64-column thumbnail of it, which is enough to tell a
gutter from drawing (and from a bubble's outline) and costs nothing. Bubbles are found as
lettered white blobs the art closes all round, on a half-size copy; when a slide has to be cut
through the art, the lettering near the cut is also found (`adapters.lettering`), so a bubble
with no closed outline is not sliced either.

Long empty stretches are squeezed and blank pieces never written. The first and last few pieces
are then shown to a junk check (scanlator credits, website banners, the title card), which is
what a chapter opens and closes on. A piece is cut back to the gutter above where its junk
starts — the last story panel often shares a slide with the credits — or deleted when nothing
above is story, and the rest renumbered.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Callable, Sequence

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from manhwatok.domain.errors import MetadataError, StorageError
from manhwatok.domain.panels import (
    CUT_SLACK,
    GUTTER_FLATNESS,
    MAX_GAP,
    MIN_GUTTER,
    MIN_PIECE,
    SLIDE_H,
    SLIDE_W,
    art_cut,
    gutter_bands,
    gutter_cut,
    is_blank,
    squeeze,
)

SAMPLE_W = 64  # columns a row is measured across: enough for a bubble's outline to show
PANELS_FILE = "panels.json"  # written last, so a half-cut folder is cut again
CUTTER_VERSION = 3  # a folder cut by any other version is cut again
LOOKAHEAD = 400  # rows below a full slide known before cutting, so a bubble there is seen whole
JUNK_SCAN = 5  # pieces at each end of a chapter shown to the junk check
TITLE_SCAN = 25  # pieces from the start in which a title card (after a cold open) is looked for

# Bubbles, measured on a copy 1/BUBBLE_SCALE the size; sizes are in full-size pixels.
BUBBLE_SCALE = 2
BRIGHT = 225  # grey level a bubble's fill is at least
DARK = 100  # grey level its lettering is at most
BUBBLE_MIN_W, BUBBLE_MIN_H = 40, 20  # smaller is a highlight in the art
BUBBLE_MAX_H = 900  # taller is a white panel inside a frame, not a bubble
BUBBLE_MIN_INK = 40  # lettering pixels a bubble holds
BUBBLE_PAD = 12  # rows kept clear above and below a bubble

# (piece, the manhwa's titles, how much of each of its rows is bare margin, whether it is at
# either end of the chapter) -> the row it stops being the story at (0: none of it is), or None
# when it is all story
JunkCheck = Callable[[Path, Sequence[str], Sequence[float], bool], int | None]
# (a stretch of the strip) -> the (top, bottom) rows of each line of lettering on it
LetteringCheck = Callable[[Image.Image], list[tuple[int, int]]]
LETTERING_GAP = 48  # rows between two lines of the same bubble
LETTERING_PAD = 32  # rows kept clear around a bubble's lettering, for the bubble around it
MARGIN_TOLERANCE = 16  # grey levels a pixel may be off the margin colour and still be margin


class PillowPanelCutter:
    """Pages in, slide-sized panels out, cached by the folder they were written to."""

    def __init__(
        self,
        width: int = SLIDE_W,
        height: int = SLIDE_H,
        flatness: float = GUTTER_FLATNESS,
        slack: int = CUT_SLACK,
        min_piece: int = MIN_PIECE,
        sample_w: int = SAMPLE_W,
        min_gutter: int = MIN_GUTTER,
        max_gap: int = MAX_GAP,
        lookahead: int = LOOKAHEAD,
        junk: JunkCheck | None = None,
        junk_scan: int = JUNK_SCAN,
        title_scan: int = TITLE_SCAN,
        lettering: LetteringCheck | None = None,
    ) -> None:
        self._width = width
        self._height = height
        self._flatness = flatness
        self._slack = slack
        self._min_piece = min_piece
        self._sample_w = sample_w
        self._min_gutter = min_gutter
        self._max_gap = max_gap
        self._lookahead = lookahead
        self._junk = junk
        self._junk_scan = junk_scan
        self._title_scan = title_scan
        self._lettering = lettering

    def cut(
        self,
        pages: list[Path],
        out_dir: Path,
        prefix: str = "panel",
        titles: Sequence[str] = (),
    ) -> list[Path]:
        """The pages cut into panels in `out_dir`, in reading order. A folder already cut is
        returned as it is: cutting is settled once, so a later part of the same chapter is the
        same split. A folder cut by an older cutter is cut again. `titles` are the manhwa's
        names, for the junk check to know its title card."""
        kept = self.cached(out_dir)
        if kept:
            return kept
        if not pages:
            return []
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            for old in out_dir.glob(f"{prefix}-*"):
                old.unlink()
        except OSError as e:
            raise StorageError(f"could not prepare panel folder {out_dir}: {e}") from e
        written: list[Path] = []
        carry: Image.Image | None = None
        for page in pages:
            carry = self._join(carry, self._scaled(page))
            carry = self._drain(carry, out_dir, prefix, written, ended=False)
        if carry is not None:
            carry = self._drain(carry, out_dir, prefix, written, ended=True)
            if carry.height and not is_blank(self.row_spreads(carry), self._flatness):
                written.append(self._write(carry, out_dir, prefix, len(written) + 1))
        written = self._drop_junk(written, out_dir, prefix, titles)
        self._save_manifest(out_dir, written)
        return written

    def cached(self, out_dir: Path) -> list[Path]:
        """What a finished cut by this cutter left here, or nothing when the cut never finished
        or was made by an older one."""
        try:
            manifest = json.loads((out_dir / PANELS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(manifest, dict) or manifest.get("cutter") != CUTTER_VERSION:
            return []
        names = manifest.get("panels")
        if not isinstance(names, list):
            return []
        found = [out_dir / str(name) for name in names]
        return found if all(p.is_file() and p.stat().st_size > 0 for p in found) else []

    def row_spreads(self, img: Image.Image) -> list[float]:
        """How far apart the lightest and darkest samples of each row are: near zero on a
        gutter, high anywhere there is drawing or lettering."""
        small = img.convert("L").resize((self._sample_w, img.height), Image.Resampling.BOX)
        data = small.tobytes()  # one byte per pixel in "L", so the rows are plain slices
        return [
            float(max(row) - min(row))
            for row in (
                data[y * self._sample_w : (y + 1) * self._sample_w] for y in range(img.height)
            )
        ]

    def bubble_rows(self, img: Image.Image) -> list[bool]:
        """Which rows cross a speech bubble: a bright blob, closed all round by the art (so not
        the margin, which reaches the page's sides), bubble-sized, with lettering inside."""
        small_w = max(1, img.width // BUBBLE_SCALE)
        small_h = max(1, img.height // BUBBLE_SCALE)
        grey = np.asarray(img.convert("L").resize((small_w, small_h), Image.Resampling.BOX))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            (grey >= BRIGHT).astype(np.uint8), connectivity=4
        )
        rows = np.zeros(img.height, dtype=bool)
        dark = grey <= DARK
        for label in range(1, count):
            x, y, w, h, _ = stats[label]
            if x == 0 or x + w >= small_w:
                continue  # reaches the side: margin or gutter, not a bubble
            if not (
                BUBBLE_MIN_W <= w * BUBBLE_SCALE
                and BUBBLE_MIN_H <= h * BUBBLE_SCALE <= BUBBLE_MAX_H
            ):
                continue
            if _enclosed_ink(labels[y : y + h, x : x + w] == label, dark[y : y + h, x : x + w]) < (
                BUBBLE_MIN_INK / BUBBLE_SCALE
            ):
                continue
            top = max(0, y * BUBBLE_SCALE - BUBBLE_PAD)
            rows[top : (y + h) * BUBBLE_SCALE + BUBBLE_PAD] = True
        return rows.tolist()

    # --- the pieces of the cut ----------------------------------------------------------

    def _scaled(self, page: Path) -> Image.Image:
        try:
            with Image.open(page) as img:
                rgb = img.convert("RGB")
        except (OSError, UnidentifiedImageError) as e:
            raise MetadataError(f"page {page.name} could not be read: {e}") from e
        if rgb.width == self._width:
            return rgb
        height = max(1, round(rgb.height * self._width / rgb.width))
        return rgb.resize((self._width, height), Image.Resampling.LANCZOS)

    @staticmethod
    def _join(carry: Image.Image | None, page: Image.Image) -> Image.Image:
        if carry is None:
            return page
        joined = Image.new("RGB", (page.width, carry.height + page.height))
        joined.paste(carry, (0, 0))
        joined.paste(page, (0, carry.height))
        return joined

    def _drain(
        self, carry: Image.Image, out_dir: Path, prefix: str, written: list[Path], ended: bool
    ) -> Image.Image:
        """Write off every complete piece at the top of the carry, and keep the remainder.
        Until the strip has `ended`, a piece waits for the rows below it to be known."""
        while carry.height:
            spreads = self.row_spreads(carry)
            kept = squeeze(spreads, self._max_gap, self._flatness, ended)
            if len(kept) > 1:
                carry = _rows_of(carry, kept)
                spreads = [spread for start, end in kept for spread in spreads[start:end]]
            if not ended and carry.height < self._height + self._lookahead:
                return carry
            if carry.height < self._height:
                return carry  # the end of the strip: all one last piece
            bubbles = self.bubble_rows(carry)
            cut = gutter_cut(
                spreads,
                self._height,
                self._slack,
                self._min_piece,
                self._flatness,
                self._min_gutter,
                bubbles,
            )
            if cut is None:
                cut = art_cut(
                    spreads, self._height, self._slack, self._min_piece, self._clear(carry, bubbles)
                )
            if not is_blank(spreads[:cut], self._flatness):
                piece = carry.crop((0, 0, carry.width, cut))
                written.append(self._write(piece, out_dir, prefix, len(written) + 1))
            carry = carry.crop((0, cut, carry.width, carry.height))
        return carry

    def _clear(self, carry: Image.Image, bubbles: list[bool]) -> list[bool]:
        """The rows a cut through the art must stay clear of: the bubbles, and every block of
        lettering within reach of the cut (lines close together are one bubble)."""
        if self._lettering is None:
            return bubbles
        top = max(0, self._height - self._slack - LETTERING_PAD - LETTERING_GAP * 4)
        bottom = min(carry.height, self._height + LETTERING_PAD + LETTERING_GAP * 4)
        lines = sorted(
            (top + first, top + last)
            for first, last in self._lettering(carry.crop((0, top, carry.width, bottom)))
        )
        blocks: list[list[int]] = []
        for first, last in lines:
            if blocks and first - blocks[-1][1] <= LETTERING_GAP:
                blocks[-1][1] = max(blocks[-1][1], last)
            else:
                blocks.append([first, last])
        clear = list(bubbles)
        for first, last in blocks:
            for row in range(max(0, first - LETTERING_PAD), min(len(clear), last + LETTERING_PAD)):
                clear[row] = True
        return clear

    def _write(self, piece: Image.Image, out_dir: Path, prefix: str, n: int) -> Path:
        path = out_dir / f"{prefix}-{n:03d}.png"
        slide = Image.new("RGB", (self._width, self._height), _edge_colour(piece))
        slide.paste(piece.crop((0, 0, piece.width, min(piece.height, self._height))), (0, 0))
        partial = path.with_name(path.name + ".part")
        try:
            slide.save(partial, format="PNG")  # the .part name tells Pillow nothing
            partial.replace(path)
        except OSError as e:
            partial.unlink(missing_ok=True)
            raise StorageError(f"could not save panel {path}: {e}") from e
        return path

    def _drop_junk(
        self, written: list[Path], out_dir: Path, prefix: str, titles: Sequence[str]
    ) -> list[Path]:
        """The pieces with the junk at either end cut off or deleted, the rest renumbered."""
        if self._junk is None or not written:
            return written
        ends = set(range(min(self._junk_scan, len(written))))
        ends |= set(range(max(0, len(written) - self._junk_scan), len(written)))
        kept = []
        for n, path in enumerate(written):
            if n in ends:
                keep = self._keep_story(path, out_dir, prefix, titles, n + 1, ends=True)
            elif n < self._title_scan:
                keep = self._keep_story(path, out_dir, prefix, titles, n + 1, ends=False)
            else:
                keep = True
            if keep:
                kept.append(path)
        renamed = []
        try:
            for n, path in enumerate(kept, 1):
                target = out_dir / f"{prefix}-{n:03d}.png"
                if path != target:
                    path.replace(target)  # only ever to a lower, already freed number
                renamed.append(target)
        except OSError as e:
            raise StorageError(f"could not renumber the panels in {out_dir}: {e}") from e
        return renamed

    def _keep_story(
        self, path: Path, out_dir: Path, prefix: str, titles: Sequence[str], n: int, ends: bool
    ) -> bool:
        """Cut a written piece back to the story above its junk; False when none of it is
        story, and the piece is then deleted. Inside the chapter the story goes on under a
        title card, so there a piece is only ever deleted whole, never cut back."""
        with Image.open(path) as img:
            slide = img.convert("RGB")
        spreads = self.row_spreads(slide)
        starts = self._junk(path, titles, _margin_rows(slide), ends)
        if starts is None:
            return True
        above = [
            (min(end, starts), start)
            for start, end in gutter_bands(spreads[:starts], self._flatness)
            if end - start >= self._min_gutter or end >= starts
        ]
        end, start = max(above, default=(0, 0))  # the lowest gutter above the junk
        cut = (start + end) // 2
        if not ends:
            cut = starts  # a whole title card, or nothing
        if cut <= 0 or is_blank(spreads[:cut], self._flatness):
            path.unlink(missing_ok=True)
            return False
        if not ends:
            return True
        self._write(slide.crop((0, 0, slide.width, cut)), out_dir, prefix, n)
        return True

    @staticmethod
    def _save_manifest(out_dir: Path, written: list[Path]) -> None:
        manifest = {"cutter": CUTTER_VERSION, "panels": [p.name for p in written]}
        try:
            (out_dir / PANELS_FILE).write_text(json.dumps(manifest), encoding="utf-8")
        except OSError as e:
            raise StorageError(f"could not save the panel list in {out_dir}: {e}") from e


def _rows_of(img: Image.Image, ranges: list[tuple[int, int]]) -> Image.Image:
    """The image with only the given half-open row ranges, stacked in order."""
    out = Image.new("RGB", (img.width, sum(end - start for start, end in ranges)))
    at = 0
    for start, end in ranges:
        out.paste(img.crop((0, start, img.width, end)), (0, at))
        at += end - start
    return out


def _margin_rows(slide: Image.Image) -> list[float]:
    """How much of each row is the slide's margin colour: near 1 across a credits page, however
    many lines of lettering it has, and low across drawing."""
    background = Image.new("RGB", (1, 1), _edge_colour(slide)).convert("L").getpixel((0, 0))
    grey = np.asarray(slide.convert("L"), dtype=np.int16)
    return (np.abs(grey - background) <= MARGIN_TOLERANCE).mean(axis=1).tolist()


def _enclosed_ink(blob: np.ndarray, dark: np.ndarray) -> int:
    """How many dark pixels sit in the holes of a blob: a bubble's lettering."""
    outside = np.pad(~blob, 1).astype(np.uint8)
    cv2.floodFill(outside, None, (0, 0), 2)
    holes = outside[1:-1, 1:-1] == 1
    return int(np.count_nonzero(holes & dark))


def _edge_colour(piece: Image.Image) -> tuple[int, int, int]:
    """The strip's own background, so a short piece is padded with page margin rather than with
    a black letterbox: the commonest colour down the piece's two side columns, which is where a
    webtoon leaves its margin. Full-bleed art has no margin, and this is then its border."""
    if not piece.height or not piece.width:
        return (255, 255, 255)
    sides = Counter()
    for x in (0, piece.width - 1):
        column = piece.crop((x, 0, x + 1, piece.height)).convert("RGB").tobytes()
        sides.update(tuple(column[at : at + 3]) for at in range(0, len(column), 3))
    return sides.most_common(1)[0][0]
