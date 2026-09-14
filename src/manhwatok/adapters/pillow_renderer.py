"""Draws post slides (style C, blur-fill) as 1080×1920 PNGs with Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

from manhwatok.adapters.layout import (
    BAR_H,
    PILL_BORDER,
    PILL_PAD_X,
    SLIDE_H,
    SLIDE_W,
    Pill,
    Placed,
    fit_inside,
    layout_cover,
    layout_end,
    layout_item,
)
from manhwatok.domain.color import hex_to_rgb, readable_accent
from manhwatok.domain.errors import StorageError
from manhwatok.domain.labels import chapter_label
from manhwatok.domain.post import ListPost

WHITE = (255, 255, 255)
DARK = (11, 11, 16)
DIM = (255, 255, 255, 77)
SIZE = (SLIDE_W, SLIDE_H)
GRADIENT_H = 920


def _load(path: Path | None) -> Image.Image | None:
    if path is None:
        return None
    try:
        with Image.open(path) as img:
            return img.convert("RGB")
    except (OSError, UnidentifiedImageError):
        return None


def _blurred(
    img: Image.Image, size: tuple[int, int], radius: float, brightness: float
) -> Image.Image:
    # blur at quarter size then scale up: same look, ~16x faster than blurring full size
    small = ImageOps.fit(img, (size[0] // 4, size[1] // 4), Image.Resampling.LANCZOS)
    small = small.filter(ImageFilter.GaussianBlur(radius / 4))
    small = ImageEnhance.Brightness(small).enhance(brightness)
    return small.resize(size, Image.Resampling.BICUBIC)


def _accent_gradient(size: tuple[int, int], accent: str) -> Image.Image:
    """Stand-in for a missing cover: accent colour fading to near-black."""
    r, g, b = hex_to_rgb(accent)
    column = Image.new("RGB", (1, 256))
    column.putdata(
        [
            (
                int(r * (1 - t / 255) * 0.6),
                int(g * (1 - t / 255) * 0.6),
                int(b * (1 - t / 255) * 0.6),
            )
            for t in range(256)
        ]
    )
    return column.resize(size, Image.Resampling.BICUBIC)


def _bottom_gradient(canvas: Image.Image) -> None:
    """Darken the lowest GRADIENT_H px: transparent → 88% black at 55% → black."""
    alpha = []
    for y in range(GRADIENT_H):
        t = y / (GRADIENT_H - 1)
        a = 0.88 * t / 0.55 if t <= 0.55 else 0.88 + 0.12 * (t - 0.55) / 0.45
        alpha.append(round(255 * a))
    mask = Image.new("L", (1, GRADIENT_H))
    mask.putdata(alpha)
    mask = mask.resize((SLIDE_W, GRADIENT_H))
    canvas.paste((0, 0, 0), (0, SLIDE_H - GRADIENT_H, SLIDE_W, SLIDE_H), mask)


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def _paste_with_shadow(canvas: Image.Image, card: Image.Image, x: int, y: int) -> None:
    """Paste an RGBA card with a soft drop shadow below it."""
    pad = 60
    shadow = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 170), (pad, pad), card.getchannel("A"))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    canvas.alpha_composite(shadow, (x - pad, y - pad + 14))
    canvas.alpha_composite(card, (x, y))


def _draw_text(draw: ImageDraw.ImageDraw, placed: Placed, color, accent) -> None:
    """Paint each line word by word, and each word run by run (its own colour), advancing x by
    each run's length — a trailing space is appended only to a word's last run, and only when
    the word isn't the last one on the line."""
    text = placed.text
    for i, base in enumerate(text.baselines(placed.y)):
        x = placed.line_x(i)
        words = text.lines[i]
        for j, word in enumerate(words):
            for k, (run_text, is_accent) in enumerate(word):
                chunk = run_text
                if k == len(word) - 1 and j != len(words) - 1:
                    chunk += " "
                draw.text(
                    (x, base),
                    chunk,
                    font=text.font,
                    fill=accent if is_accent else color,
                    anchor="ls",
                )
                x += text.font.getlength(chunk)


def _draw_pill(draw: ImageDraw.ImageDraw, pill: Pill, accent, filled: bool) -> None:
    b = pill.box
    rect = (b.x, b.y, b.right, b.bottom)
    if filled:
        draw.rounded_rectangle(rect, radius=b.h // 2, fill=accent)
        color = DARK
    else:
        draw.rounded_rectangle(rect, radius=b.h // 2, outline=accent, width=PILL_BORDER)
        color = accent
    baseline = pill.text_top - pill.text.ink_top
    draw.text(
        (b.x + PILL_PAD_X, baseline),
        pill.text.line_text(0),
        font=pill.text.font,
        fill=color,
        anchor="ls",
    )


class PillowRenderer:
    def render(self, post: ListPost, covers: dict[int, Path | None], out_dir: Path) -> list[Path]:
        """Write 01.png (cover) … NN.png (end slide) into out_dir, replacing old slides."""
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            for old in out_dir.glob("[0-9][0-9].png"):
                old.unlink()
        except OSError as e:
            raise StorageError(f"could not prepare slide folder {out_dir}: {e}") from e
        images = {m_id: _load(path) for m_id, path in covers.items()}
        slides = [self.cover_slide(post, images)]
        slides += [self.item_slide(post, i, images) for i in range(len(post.items))]
        slides.append(self.end_slide(post, images))
        paths = []
        for n, slide in enumerate(slides, 1):
            path = out_dir / f"{n:02d}.png"
            try:
                slide.convert("RGB").save(path)
            except OSError as e:
                raise StorageError(f"could not save slide {path}: {e}") from e
            paths.append(path)
        return paths

    def item_slide(
        self, post: ListPost, index: int, images: dict[int, Image.Image | None]
    ) -> Image.Image:
        item = post.items[index]
        m = item.manhwa
        accent = hex_to_rgb(readable_accent(m.cover_color, post.accent))
        img = images.get(m.anilist_id)
        canvas = (
            _blurred(img, SIZE, 36, 0.42)
            if img
            else _accent_gradient(SIZE, readable_accent(m.cover_color, post.accent))
        ).convert("RGBA")
        layout = layout_item(index + 1, m.title, chapter_label(m), item.hook)
        src = img or _accent_gradient((460, 650), readable_accent(m.cover_color, post.accent))
        box = fit_inside(src.width, src.height, layout.cover_area)
        card = _rounded(src.resize((box.w, box.h), Image.Resampling.LANCZOS), 24)
        _paste_with_shadow(canvas, card, box.x, box.y)
        _bottom_gradient(canvas)
        draw = ImageDraw.Draw(canvas)
        _draw_text(draw, layout.rank, accent, accent)
        _draw_text(draw, layout.name, WHITE, accent)
        _draw_pill(draw, layout.pill, accent, filled=False)
        if layout.hook:
            _draw_text(draw, layout.hook, WHITE, accent)
        return canvas

    def cover_slide(self, post: ListPost, images: dict[int, Image.Image | None]) -> Image.Image:
        accent = hex_to_rgb(readable_accent(post.accent))
        first = post.items[0].manhwa
        img = images.get(first.anilist_id)
        canvas = (
            _blurred(img, SIZE, 36, 0.42)
            if img
            else _accent_gradient(SIZE, readable_accent(post.accent))
        ).convert("RGBA")
        fan = post.items[:3]
        # (item index, size, rotation, centre x, top y); drawn back to front so the centre card is on top
        slots = {
            0: ((440, 624), 0, SLIDE_W // 2, 312),
            1: ((416, 588), 11, SLIDE_W // 2 - 250, 384),
            2: ((416, 588), -11, SLIDE_W // 2 + 250, 384),
        }
        for i in [i for i in (1, 2, 0) if i < len(fan)]:
            size, angle, cx, top = slots[i]
            m = fan[i].manhwa
            src = images.get(m.anilist_id) or _accent_gradient(
                (460, 650), readable_accent(m.cover_color, post.accent)
            )
            card = _rounded(ImageOps.fit(src, size, Image.Resampling.LANCZOS), 20)
            rotated = card.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
            _paste_with_shadow(
                canvas, rotated, cx - rotated.width // 2, top - (rotated.height - size[1]) // 2
            )
        _bottom_gradient(canvas)
        layout = layout_cover(post.title, len(post.items))
        draw = ImageDraw.Draw(canvas)
        _draw_pill(draw, layout.kicker, accent, filled=True)
        _draw_text(draw, layout.title, WHITE, accent)
        # Draw active segment first, then composite DIM segments with alpha blending
        for i, seg in enumerate(layout.bar):
            if i == 0:
                draw.rounded_rectangle(
                    (seg.x, seg.y, seg.right, seg.bottom),
                    radius=BAR_H // 2,
                    fill=accent,
                )
        # DIM segments with proper alpha blending
        dim_layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
        dim_draw = ImageDraw.Draw(dim_layer)
        for i, seg in enumerate(layout.bar):
            if i > 0:
                dim_draw.rounded_rectangle(
                    (seg.x, seg.y, seg.right, seg.bottom),
                    radius=BAR_H // 2,
                    fill=DIM,
                )
        canvas.alpha_composite(dim_layer)
        return canvas

    def end_slide(self, post: ListPost, images: dict[int, Image.Image | None]) -> Image.Image:
        accent = hex_to_rgb(readable_accent(post.accent))
        tiles = [images.get(it.manhwa.anilist_id) for it in post.items[:4]]
        tiles = [t for t in tiles if t is not None]
        if tiles:
            canvas = Image.new("RGBA", SIZE, (0, 0, 0, 255))
        else:
            canvas = _accent_gradient(SIZE, readable_accent(post.accent)).convert("RGBA")
        if tiles:
            half = (SLIDE_W // 2, SLIDE_H // 2)
            for k in range(4):
                tile = _blurred(tiles[k % len(tiles)], half, 30, 0.30)
                canvas.paste(tile, ((k % 2) * half[0], (k // 2) * half[1]))
        layout = layout_end([it.manhwa.title for it in post.items])
        draw = ImageDraw.Draw(canvas)
        _draw_text(draw, layout.title, WHITE, accent)
        for i, row in enumerate(layout.rows):
            if row.number:
                item = post.items[i].manhwa
                num_color = hex_to_rgb(readable_accent(item.cover_color, post.accent))
                _draw_text(draw, row.number, num_color, num_color)
            _draw_text(draw, row.name, WHITE, accent)
        _draw_text(draw, layout.follow, WHITE, accent)
        return canvas
