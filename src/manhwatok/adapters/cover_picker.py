"""Which picture makes the cover, and which part of it: the most striking panel, not a page.

A chapter's slides are pages: several panels, white or black gutters, speech bubbles. So each
picture is first cut into its drawn panels (runs of rows that aren't one flat colour), and a
tall panel into overlapping windows; every piece is scored and the best one is the cover's focus.

CLIP, run offline through onnxruntime (already here for RapidOCR), scores each piece against
words describing a good cover and words describing a bad one — a black page, speech bubbles, a
text box, a blur. Its model (~150MB, ViT-B/32, quantized) is downloaded once, on first use.
Without the `pick` extra, or when the model can't be had, a plain measure stands in: a drawn,
colourful, sharp panel beats a black page, a blank one or a smear.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable

import httpx
import numpy as np
from PIL import Image, ImageFilter, ImageOps

from manhwatok.ports.picker import Focus

MODEL_URL = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main"
MODEL_FILES = {
    "vision.onnx": "onnx/vision_model_quantized.onnx",
    "text.onnx": "onnx/text_model_quantized.onnx",
    "tokenizer.json": "tokenizer.json",
}
GOOD = (
    "an epic dramatic manhwa action scene",
    "a striking close-up of a manhwa character's intense face",
    "beautiful detailed colorful webtoon art of a character",
    "a powerful character posing with a glowing aura",
    "a cool anime character looking at the viewer",
)
BAD = (
    "a blank white page",
    "a black page",
    "a page full of text",
    "a speech bubble with text",
    "a blue game system text box",
    "a comic page with many small panels",
    "a blurry image",
    "a plain background with nothing on it",
    "a sound effect written in big letters",
)
SIDE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
MID_GREY = 110.0  # the brightness a drawn panel sits around, between black pages and blank ones
# Finding panels: a row is gutter when it is one flat, near-white or near-black colour (a flat
# coloured sky is art, not gutter); a panel is a run of other rows at least MIN_PANEL px tall
# and wide (smaller is a stray mark, or too small to fill a cover).
FLAT, FLAT_SHARE, DARK, LIGHT, MIN_PANEL, SCAN_W = 14.0, 0.9, 30.0, 225.0, 240, 540
# A panel taller than this many widths is cut into windows this many widths tall, overlapping
# by half, so a face at its top isn't scored as part of the whole long strip.
TALL, WINDOW = 1.4, 1.1

# Lettering: CLIP's best few pieces are read for text. Rows of text at a piece's edge are cut
# off when at least CLEAR_KEEP of it is left; text still inside costs its share of the piece's
# area times TEXT_COST, up to TEXT_MAX (CLIP's scores run 0–1).
READ_BEST, TEXT_MARGIN, CLEAR_KEEP, TEXT_COST, TEXT_MAX = 6, 16, 0.55, 8.0, 0.6
SAME_PIECE = 0.3  # two pieces of one picture overlapping more than this are the same shot
# A small piece scores as well as a big one to CLIP, but blown up to a cover it goes soft: one
# whose shorter side is under SMALL_SIDE px loses up to SMALL_COST.
SMALL_SIDE, SMALL_COST = 500, 0.3

Box = tuple[int, int, int, int]
ProgressFn = Callable[[str], None]
TextFinder = Callable[[Image.Image], list[Box]]


def _runs(flags: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """[start, end) of each run of True in `flags` at least `min_len` long."""
    runs, start = [], None
    for n, on in enumerate([*flags, False]):
        if on and start is None:
            start = n
        elif not on and start is not None:
            if n - start >= min_len:
                runs.append((start, n))
            start = None
    return runs


def _gutter(grey: np.ndarray, axis: int) -> np.ndarray:
    """Which rows (axis=1) or columns (axis=0) of `grey` are gutter: white or black, and flat
    over nearly all their length — a bubble or an arm may cross a gutter here and there."""
    middle = np.median(grey, axis=axis)
    near = np.abs(grey - np.expand_dims(middle, axis)) <= FLAT
    return (near.mean(axis=axis) >= FLAT_SHARE) & ((middle <= DARK) | (middle >= LIGHT))


def panels(img: Image.Image) -> list[Box]:
    """The drawn panels on a page, top to bottom and left to right, each trimmed of its flat
    margins. A picture with no gutters is one panel: itself."""
    scale = img.width / SCAN_W
    small = np.asarray(
        img.convert("L").resize((SCAN_W, max(1, round(img.height / scale)))), np.float32
    )
    min_len = max(1, round(MIN_PANEL / scale))
    found = []
    for top, bottom in _runs(~_gutter(small, axis=1), min_len):
        # Panels side by side have a gutter column between them.
        for left, right in _runs(~_gutter(small[top:bottom], axis=0), min_len):
            found.append(
                (
                    round(left * scale),
                    round(top * scale),
                    min(img.width, round(right * scale)),
                    min(img.height, round(bottom * scale)),
                )
            )
    return found


def pieces(img: Image.Image) -> list[Box]:
    """Every part of `img` worth scoring as a cover: each panel, and a tall panel's windows."""
    found = []
    for box in panels(img):
        left, top, right, bottom = box
        found.append(box)
        w, h = right - left, bottom - top
        if h > TALL * w:
            step, tall = round(WINDOW * w / 2), round(WINDOW * w)
            y = top
            while y + tall < bottom:
                found.append((left, y, right, y + tall))
                y += step
            found.append((left, bottom - tall, right, bottom))
    return found


def clear_of_text(box: Box, text: list[Box]) -> tuple[Box, float]:
    """`box` cut down to its tallest stretch of rows with no text (`text` in the box's own
    pixels) when that keeps enough of it, and the share of what's left that text covers."""
    left, top, right, bottom = box
    w, h = right - left, bottom - top
    if not text:
        return box, 0.0
    blocked = sorted((max(0, y0 - TEXT_MARGIN), min(h, y1 + TEXT_MARGIN)) for _, y0, _, y1 in text)
    free, y = [], 0
    for y0, y1 in blocked:
        if y0 > y:
            free.append((y, y0))
        y = max(y, y1)
    if y < h:
        free.append((y, h))
    a, b = max(free, key=lambda span: span[1] - span[0], default=(0, 0))
    if b - a >= max(CLEAR_KEEP * h, MIN_PANEL):
        return (left, top + a, right, top + b), 0.0
    covered = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in text)
    return box, min(1.0, covered / max(1, w * h))


def _overlap(a: Box, b: Box) -> float:
    """How much of the smaller of two boxes the other covers, 0–1."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / max(1, smaller)


def _small(box: Box) -> float:
    """What a piece's size costs it: nothing from SMALL_SIDE up, SMALL_COST at nothing."""
    side = min(box[2] - box[0], box[3] - box[1])
    return SMALL_COST * max(0.0, 1 - side / SMALL_SIDE)


def _distinct(ranked: list[Focus], count: int) -> list[Focus]:
    """The first `count` of `ranked` that don't mostly repeat a better one."""
    kept: list[Focus] = []
    for one in ranked:
        if all(one.index != k.index or _overlap(one.box, k.box) <= SAME_PIECE for k in kept):
            kept.append(one)
        if len(kept) == count:
            break
    return kept


def _focus(
    images: list[Image.Image],
    score: Callable[[list[Image.Image]], list[float]],
    find_text: TextFinder | None = None,
    count: int = 1,
) -> list[Focus]:
    """Up to `count` of the best-scoring, distinct pieces of any of `images`, best first; a
    picture with no panel found counts whole. With `find_text`, the best few are read, cut clear
    of their lettering and scored again."""
    where = [
        Focus(n, box)
        for n, img in enumerate(images)
        for box in (pieces(img) or [(0, 0, img.width, img.height)])
    ]
    if len(where) <= 1:
        return where
    scores = score([images[f.index].crop(f.box) for f in where])
    scores = [v - _small(f.box) for v, f in zip(scores, where)]
    ranked = [where[k] for k in sorted(range(len(where)), key=lambda k: (-scores[k], k))]
    if find_text is None:
        return _distinct(ranked, count)
    read = []
    for f in _distinct(ranked, max(READ_BEST, 2 * count)):
        cleared, covered = clear_of_text(f.box, find_text(images[f.index].crop(f.box)))
        read.append((Focus(f.index, cleared), covered))
    again = score([images[f.index].crop(f.box) for f, _ in read])
    final = [
        again[i] - min(TEXT_MAX, TEXT_COST * covered) - _small(f.box)
        for i, (f, covered) in enumerate(read)
    ]
    order = sorted(range(len(read)), key=lambda i: (-final[i], i))
    return _distinct([read[i][0] for i in order], count)


def find_text(img: Image.Image) -> list[Box]:
    """Every line of lettering on `img`, as boxes; none when RapidOCR can't read it."""
    from manhwatok.adapters.lettering import rapid_ocr

    try:
        found, _ = rapid_ocr()(
            np.asarray(img.convert("RGB")), use_det=True, use_cls=False, use_rec=False
        )
    except Exception:  # noqa: BLE001 — unread lettering only makes the pick a little worse
        return []
    return [
        (
            int(min(p[0] for p in quad)),
            int(min(p[1] for p in quad)),
            int(max(p[0] for p in quad)),
            int(max(p[1] for p in quad)),
        )
        for quad in found or []
    ]


def _plain_score(img: Image.Image) -> float:
    """Higher for a drawn, colourful, sharp picture; lowest for a flat black or white page."""
    small = np.asarray(img.convert("RGB").resize((128, 228), Image.Resampling.BOX), np.float32)
    r, g, b = small[..., 0], small[..., 1], small[..., 2]
    brightness = float(small.mean())
    # Hasler & Süsstrunk's colourfulness, roughly 0 (grey) to 100+ (vivid).
    rg, yb = r - g, 0.5 * (r + g) - b
    colour = float(np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean()))
    edges = np.asarray(img.convert("L").resize((128, 228)).filter(ImageFilter.FIND_EDGES))
    detail = float(edges.std())
    return detail + 0.5 * colour - 0.5 * abs(brightness - MID_GREY)


class PlainPicker:
    """Scores by a measure of the picture itself: no model, no download."""

    def focus(self, images: list[Image.Image], count: int = 1) -> list[Focus]:
        return _focus(images, lambda crops: [_plain_score(c) for c in crops], count=count)


def pixels(img: Image.Image) -> np.ndarray:
    """`img` as CLIP takes it: 224×224 from the centre, scaled to the model's mean and spread,
    channels first."""
    square = ImageOps.fit(img.convert("RGB"), (SIDE, SIDE), Image.Resampling.BICUBIC)
    data = (np.asarray(square, np.float32) / 255.0 - MEAN) / STD
    return data.transpose(2, 0, 1)


def _unit(rows: np.ndarray) -> np.ndarray:
    return rows / np.linalg.norm(rows, axis=-1, keepdims=True)


class ClipPicker:
    """Scores by how much more each piece looks like GOOD than like BAD, to CLIP. Falls back to
    the plain measure — never failing a render — when the model can't be loaded or run."""

    def __init__(
        self,
        model_dir: Path,
        progress: ProgressFn | None = None,
        text: TextFinder | None = find_text,
    ) -> None:
        self._dir = model_dir
        self._text = text
        self._progress = progress or (lambda _: None)
        self._vision: Any = None
        self._words: np.ndarray | None = None  # unit text embeddings, GOOD then BAD
        self._broken = False

    def focus(self, images: list[Image.Image], count: int = 1) -> list[Focus]:
        if not self._broken:
            try:
                return _focus(images, self.scores, self._text, count)
            except Exception as e:  # noqa: BLE001 — a bad model must not cost the post its cover
                self._broken = True
                self._progress(f"cover picker unavailable ({e}) — picking by brightness and colour")
        return PlainPicker().focus(images, count)

    def scores(self, images: list[Image.Image]) -> list[float]:
        self._load()
        scores: list[float] = []
        for start in range(0, len(images), 32):
            batch = np.stack([pixels(img) for img in images[start : start + 32]])
            (seen,) = self._vision.run(["image_embeds"], {"pixel_values": batch})
            sims = _unit(seen) @ self._words.T * 100.0
            # How sure CLIP is that the piece is one of the good kinds rather than a bad one.
            odds = np.exp(sims - sims.max(axis=1, keepdims=True))
            good = odds[:, : len(GOOD)].sum(axis=1) / odds.sum(axis=1)
            scores += [float(v) for v in good]
        return scores

    def _load(self) -> None:
        if self._vision is not None:
            return
        import onnxruntime
        from tokenizers import Tokenizer

        self._download()
        options = ["CPUExecutionProvider"]
        text = onnxruntime.InferenceSession(str(self._dir / "text.onnx"), providers=options)
        tokenizer = Tokenizer.from_file(str(self._dir / "tokenizer.json"))
        rows = []
        for phrase in (*GOOD, *BAD):
            # One phrase at a time: the model has no attention mask, so padding would count.
            ids = np.array([tokenizer.encode(phrase).ids], dtype=np.int64)
            (embed,) = text.run(["text_embeds"], {"input_ids": ids})
            rows.append(embed[0])
        self._words = _unit(np.stack(rows))
        self._vision = onnxruntime.InferenceSession(
            str(self._dir / "vision.onnx"), providers=options
        )

    def _download(self) -> None:
        missing = [name for name in MODEL_FILES if not (self._dir / name).is_file()]
        if not missing:
            return
        self._progress("downloading the cover picker's model (~150MB, once)…")
        self._dir.mkdir(parents=True, exist_ok=True)
        for name in missing:
            part = self._dir / f"{name}.part"
            with httpx.stream(
                "GET", f"{MODEL_URL}/{MODEL_FILES[name]}", follow_redirects=True, timeout=60
            ) as response:
                response.raise_for_status()
                with part.open("wb") as out:
                    for chunk in response.iter_bytes(1 << 20):
                        out.write(chunk)
            part.replace(self._dir / name)


def build_picker(model_dir: Path, progress: ProgressFn | None = None) -> ClipPicker | PlainPicker:
    """CLIP when the `pick` extra is installed, else the plain measure."""
    if importlib.util.find_spec("tokenizers") is None:
        return PlainPicker()
    return ClipPicker(model_dir, progress)
