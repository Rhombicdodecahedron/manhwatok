"""The middle and end slides of the post kinds beyond a list: versus, guess, characters.
A similar post's slides are a list post's."""

from __future__ import annotations

from typing import Callable

from PIL import Image, ImageDraw

from manhwatok.adapters.fonts import display
from manhwatok.adapters.layout import HALF, SLIDE_W, layout_versus
from manhwatok.adapters.pillow_renderer import (
    DARK,
    SIZE,
    WHITE,
    _accent_gradient,
    _Art,
    _best_piece,
    _bottom_gradient,
    _byline,
    _crop_to,
    _draw_byline,
    _draw_pill,
    _draw_text,
    _gradient_at,
)
from manhwatok.domain.color import hex_to_rgb, readable_accent
from manhwatok.domain.labels import chapter_label
from manhwatok.domain.models import PostKind
from manhwatok.domain.post import ListPost, PostItem
from manhwatok.ports.picker import PicturePicker

ItemSlide = Callable[[ListPost, int, dict], Image.Image]
# How far each half's scrim reaches up from its text: the top half's toward the badge.
TOP_SCRIM, BOTTOM_SCRIM = 520, 760
LINE = 6  # half the accent line between the halves


def _art(loaded: dict[int, _Art], item: PostItem) -> _Art:
    return loaded.get(item.manhwa.anilist_id) or _Art(None, None, None, None)


def _half(post: ListPost, item: PostItem, loaded, picker) -> Image.Image:
    """One side of a versus slide: the title's best piece, filling half the slide."""
    piece = _best_piece(_art(loaded, item), picker)
    size = (SLIDE_W, HALF)
    if piece is None:
        return _accent_gradient(size, readable_accent(item.manhwa.cover_color, post.accent))
    return _crop_to(piece, size, 0.3)


def versus_slide(
    post: ListPost, pair: tuple[PostItem, PostItem], loaded, picker: PicturePicker | None
) -> Image.Image:
    """Two titles, one above the other, split by an accent line with a round VS on it."""
    a, b = pair
    accent = hex_to_rgb(readable_accent(post.accent))
    canvas = Image.new("RGBA", SIZE, (*DARK, 255))
    canvas.paste(_half(post, a, loaded, picker).convert("RGBA"), (0, 0))
    canvas.paste(_half(post, b, loaded, picker).convert("RGBA"), (0, HALF))
    # Each half darkens toward its own text: the top one toward the badge, the bottom one down.
    _gradient_at(canvas, HALF - TOP_SCRIM, TOP_SCRIM)
    _bottom_gradient(canvas, BOTTOM_SCRIM)
    layout = layout_versus(
        a.manhwa.title, chapter_label(a.manhwa), b.manhwa.title, chapter_label(b.manhwa),
        _byline(post),
    )
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, HALF - LINE, SLIDE_W, HALF + LINE), fill=accent)
    bx = layout.badge
    draw.ellipse((bx.x, bx.y, bx.right, bx.bottom), fill=accent, outline=DARK, width=8)
    draw.text((bx.x + bx.w // 2, bx.y + bx.h // 2), "VS", font=display(88), fill=DARK, anchor="mm")
    for name, pill in ((layout.a_name, layout.a_pill), (layout.b_name, layout.b_pill)):
        _draw_text(draw, name, WHITE, accent)
        _draw_pill(draw, pill, accent, filled=False)
    _draw_byline(canvas, layout.byline)
    return canvas


def _pairs(items: list[PostItem]) -> list[tuple[PostItem, PostItem]]:
    return [(items[i], items[i + 1]) for i in range(0, len(items) - 1, 2)]


def end_names(post: ListPost) -> list[str]:
    """The end slide's recap rows, per kind."""
    if post.kind is PostKind.VERSUS:
        return [f"{a.manhwa.title} vs {b.manhwa.title}" for a, b in _pairs(post.items)]
    return [i.manhwa.title for i in post.items]


def middle_slides(
    post: ListPost, loaded, picker: PicturePicker | None, item_slide: ItemSlide
) -> list[Image.Image]:
    """The slides between cover and end, per kind."""
    if post.kind is PostKind.VERSUS:
        return [versus_slide(post, pair, loaded, picker) for pair in _pairs(post.items)]
    return [item_slide(post, i, loaded) for i in range(len(post.items))]
