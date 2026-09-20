"""Cuts a chapter's pages into slides.

A webtoon chapter is one tall strip, delivered as pages that are themselves arbitrary slices of
it — a page boundary means nothing, and a panel often straddles two. So the pages are joined in
reading order, scaled to the slide's width, and cut wherever `domain.panels` says it is safe:
in a gutter, never through a bubble or a face.

The strip is never held whole. A chapter at 1080 wide is around 100 000 rows, so pages are
added to a carry image and pieces are written off the top of it as soon as they are complete.
What each row holds is measured on a 16-column thumbnail of it, which is enough to tell a
gutter from drawing and costs nothing.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from manhwatok.domain.errors import MetadataError, StorageError
from manhwatok.domain.panels import (
    CUT_SLACK,
    GUTTER_FLATNESS,
    MIN_PIECE,
    SLIDE_H,
    SLIDE_W,
    next_cut,
)

SAMPLE_W = 16  # columns a row is measured across
PANELS_FILE = "panels.json"  # written last, so a half-cut folder is cut again


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
    ) -> None:
        self._width = width
        self._height = height
        self._flatness = flatness
        self._slack = slack
        self._min_piece = min_piece
        self._sample_w = sample_w

    def cut(self, pages: list[Path], out_dir: Path, prefix: str = "panel") -> list[Path]:
        """The pages cut into panels in `out_dir`, in reading order. A folder already cut is
        returned as it is: cutting is settled once, so a later part of the same chapter is the
        same split. Changing the cutter's settings only changes chapters cut afterwards."""
        kept = self.cached(out_dir)
        if kept:
            return kept
        if not pages:
            return []
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StorageError(f"could not prepare panel folder {out_dir}: {e}") from e
        written: list[Path] = []
        carry: Image.Image | None = None
        for page in pages:
            carry = self._join(carry, self._scaled(page))
            carry = self._drain(carry, out_dir, prefix, written)
        if carry is not None and carry.height:
            written.append(self._write(carry, out_dir, prefix, len(written) + 1))
        self._save_manifest(out_dir, written)
        return written

    def cached(self, out_dir: Path) -> list[Path]:
        """What a finished cut left here, or nothing when the cut never finished."""
        try:
            names = json.loads((out_dir / PANELS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
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
        self, carry: Image.Image, out_dir: Path, prefix: str, written: list[Path]
    ) -> Image.Image:
        """Write off every complete piece at the top of the carry, and keep the remainder."""
        while carry.height:
            cut = next_cut(
                self.row_spreads(carry), self._height, self._slack, self._min_piece, self._flatness
            )
            if cut is None:
                return carry
            written.append(
                self._write(carry.crop((0, 0, carry.width, cut)), out_dir, prefix, len(written) + 1)
            )
            carry = carry.crop((0, cut, carry.width, carry.height))
        return carry

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

    @staticmethod
    def _save_manifest(out_dir: Path, written: list[Path]) -> None:
        try:
            (out_dir / PANELS_FILE).write_text(
                json.dumps([p.name for p in written]), encoding="utf-8"
            )
        except OSError as e:
            raise StorageError(f"could not save the panel list in {out_dir}: {e}") from e


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
