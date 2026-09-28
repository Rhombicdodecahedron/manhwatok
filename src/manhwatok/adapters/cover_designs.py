"""The cover designs beyond the first three: four for a list post, four for a chapter post.

Each draws a cover's art — the list post's shared text (`PillowRenderer._cover_text`) or the
chapter post's (`chapter_text`) goes on top — except the magazine cover, which lays out its own
text. Pictures come in as pieces: a picture and the part of it the picker chose.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageEnhance

from manhwatok.adapters.layout import (
    BAR_H,
    SLIDE_W,
    Box,
    fit_inside,
    layout_chapter_cover,
    layout_magazine,
    layout_number,
    layout_tease,
)
from manhwatok.adapters.fonts import bold
from manhwatok.adapters.pillow_renderer import (
    COVER_BLUR,
    COVER_DIM,
    COVER_GRADIENT_H,
    DARK,
    DIM,
    FAN_GRADIENT_H,
    SIZE,
    WHITE,
    Piece,
    _accent_gradient,
    _Art,
    _best_piece,
    _blurred,
    _bottom_gradient,
    _byline,
    _crop_to,
    _draw_byline,
    _draw_pill,
    _draw_text,
    _focused,
    _full_bleed,
    _paste_with_shadow,
    _rounded,
)
from manhwatok.domain.chapter import chapter_kicker
from manhwatok.domain.color import hex_to_rgb, readable_accent
from manhwatok.domain.models import ChapterCoverStyle, CoverStyle
from manhwatok.domain.post import ListPost, cover_kicker
from manhwatok.ports.picker import PicturePicker

STROKE = 10  # the dark outline round a giant number, so it reads on any art
NUMBER_DIM = 0.55
SPLIT_GUTTER = 6
# Podium cards: (rank, size, centre x, top y); drawn 2, 3, then 1 so the winner is on top.
PODIUM = (
    (2, (330, 467), SLIDE_W // 2 - 300, 400),
    (3, (330, 467), SLIDE_W // 2 + 300, 400),
    (1, (420, 594), SLIDE_W // 2, 240),
)
BADGE_R = 58
CINEMA_Y, CINEMA_H, CINEMA_LINE = 400, 540, 6
# Triptych strips: size inside the frame, frame, rotation, first top, step down.
STRIP, FRAME, STRIP_TILT, STRIP_TOP, STRIP_STEP = (1000, 260), 8, (-3, 2, -2), 140, 256
TEASE_BLUR, TEASE_DIM = 48, 0.45
PAGE_MAX, PAGE_BORDER, PAGE_TILT, PAGE_Y = (820, 900), 12, -4, 560


def _art_of(post: ListPost, loaded: dict[int, _Art], index: int) -> _Art:
    """The art of pick `index`, counting round when the post has fewer."""
    m = post.items[index % len(post.items)].manhwa
    return loaded.get(m.anilist_id) or _Art(None, None, None, None)


def _framed(img: Image.Image, border: int, angle: float) -> Image.Image:
    """`img` in a white border, turned by `angle` degrees."""
    frame = Image.new("RGBA", (img.width + 2 * border, img.height + 2 * border), (*WHITE, 255))
    frame.paste(img.convert("RGBA"), (border, border))
    return frame.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)


# --- list post -------------------------------------------------------------------------------


def number_art(post: ListPost, loaded: dict[int, _Art], picker: PicturePicker | None) -> Image.Image:
    """The first pick's best piece, dimmed, under the post's count drawn giant."""
    accent_hex = readable_accent(post.accent)
    piece = _best_piece(_art_of(post, loaded, 0), picker)
    canvas = _focused(*piece, accent_hex) if piece else _full_bleed(None, accent_hex)
    canvas = ImageEnhance.Brightness(canvas.convert("RGB")).enhance(NUMBER_DIM).convert("RGBA")
    _bottom_gradient(canvas, COVER_GRADIENT_H)
    placed = layout_number(len(post.items))
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (placed.line_x(0), placed.text.baselines(placed.y)[0]),
        placed.text.line_text(0),
        font=placed.text.font,
        fill=hex_to_rgb(accent_hex),
        stroke_width=STROKE,
        stroke_fill=DARK,
        anchor="ls",
    )
    return canvas


def split_art(post: ListPost, loaded: dict[int, _Art], picker: PicturePicker | None) -> Image.Image:
    """The first three picks' best pieces as three tall slices, edge to edge."""
    canvas = Image.new("RGBA", SIZE, (0, 0, 0, 255))
    width = (SLIDE_W - 2 * SPLIT_GUTTER) // 3
    for k in range(3):
        m = post.items[k % len(post.items)].manhwa
        piece = _best_piece(_art_of(post, loaded, k), picker)
        size = (width, SIZE[1])
        if piece:
            tile = _crop_to(piece, size)
        else:
            tile = _accent_gradient(size, readable_accent(m.cover_color, post.accent))
        canvas.paste(tile.convert("RGBA"), (k * (width + SPLIT_GUTTER), 0))
    _bottom_gradient(canvas, COVER_GRADIENT_H)
    return canvas


def podium_art(post: ListPost, loaded: dict[int, _Art]) -> Image.Image:
    """The first three picks' covers on a podium — the first biggest and highest — each with its
    rank in a badge, over the first one's blur."""
    accent_hex = readable_accent(post.accent)
    accent = hex_to_rgb(accent_hex)
    first = _art_of(post, loaded, 0)
    backdrop = first.custom or first.cover
    canvas = (
        _blurred(backdrop, SIZE, COVER_BLUR, COVER_DIM)
        if backdrop
        else _accent_gradient(SIZE, accent_hex)
    ).convert("RGBA")
    for rank, size, cx, top in PODIUM:
        if rank > len(post.items):
            continue
        m = post.items[rank - 1].manhwa
        art = _art_of(post, loaded, rank - 1)
        src = art.custom or art.cover
        tile = (
            _crop_to((src, (0, 0, src.width, src.height)), size, 0.3)
            if src
            else _accent_gradient(size, readable_accent(m.cover_color, post.accent))
        )
        card = _rounded(tile, 20)
        x = cx - size[0] // 2
        _paste_with_shadow(canvas, card, x, top)
        draw = ImageDraw.Draw(canvas)
        centre = (x + BADGE_R // 3, top + BADGE_R // 3)
        draw.ellipse(
            (centre[0] - BADGE_R, centre[1] - BADGE_R, centre[0] + BADGE_R, centre[1] + BADGE_R),
            fill=accent,
            outline=DARK,
            width=4,
        )
        draw.text(centre, str(rank), font=bold(68), fill=DARK, anchor="mm")
    _bottom_gradient(canvas, FAN_GRADIENT_H)
    return canvas


def magazine_slide(
    post: ListPost, loaded: dict[int, _Art], picker: PicturePicker | None
) -> Image.Image:
    """A dark page: the title big from the top, an accent rule with the count, then the first
    pick's best piece as a card down to the caption line. Draws its own text."""
    accent_hex = readable_accent(post.accent)
    accent = hex_to_rgb(accent_hex)
    canvas = Image.new("RGBA", SIZE, (*DARK, 255))
    glow = _accent_gradient(SIZE, accent_hex).convert("RGBA")
    glow.putalpha(70)
    canvas.alpha_composite(glow)
    layout = layout_magazine(post.title, len(post.items), _byline(post), kicker=cover_kicker(post))
    piece = _best_piece(_art_of(post, loaded, 0), picker)
    area = layout.art
    if piece:
        # The box is the design: the piece fills it, cut round where a face would sit.
        card = _rounded(_crop_to(piece, (area.w, area.h), 0.3), 24)
        _paste_with_shadow(canvas, card, area.x, area.y)
    draw = ImageDraw.Draw(canvas)
    _draw_text(draw, layout.title, WHITE, accent)
    r = layout.rule
    draw.rectangle((r.x, r.y, r.right, r.bottom), fill=accent)
    _draw_text(draw, layout.kicker, accent, accent)
    _draw_byline(canvas, layout.byline)
    return canvas


def list_cover_art(
    style: CoverStyle, post: ListPost, loaded: dict[int, _Art], picker: PicturePicker | None
) -> Image.Image | None:
    """The art of one of this module's list covers; None for a style it doesn't draw."""
    if style is CoverStyle.NUMBER:
        return number_art(post, loaded, picker)
    if style is CoverStyle.SPLIT:
        return split_art(post, loaded, picker)
    if style is CoverStyle.PODIUM:
        return podium_art(post, loaded)
    return None


# --- chapter post ----------------------------------------------------------------------------


def chapter_text(canvas: Image.Image, post: ListPost, kicker_text: str | None = None) -> Image.Image:
    """The text every chapter cover shares: pill, title, part bar and byline."""
    part = post.chapter
    accent = hex_to_rgb(readable_accent(post.accent))
    layout = layout_chapter_cover(
        part.manhwa_title, part.number, part.part, part.parts, _byline(post), kicker_text
    )
    draw = ImageDraw.Draw(canvas)
    _draw_pill(draw, layout.kicker, accent, filled=True)
    _draw_text(draw, layout.title, WHITE, accent)
    dim_layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    dim_draw = ImageDraw.Draw(dim_layer)
    for i, seg in enumerate(layout.bar):
        rect = (seg.x, seg.y, seg.right, seg.bottom)
        if i == layout.lit:
            draw.rounded_rectangle(rect, radius=BAR_H // 2, fill=accent)
        else:
            dim_draw.rounded_rectangle(rect, radius=BAR_H // 2, fill=DIM)
    canvas.alpha_composite(dim_layer)
    _draw_byline(canvas, layout.byline)
    return canvas


def _crop(piece: Piece) -> Image.Image:
    img, box = piece
    return img.crop(box)


def focus_cover(post: ListPost, pieces: list[Piece]) -> Image.Image:
    accent_hex = readable_accent(post.accent)
    canvas = _focused(*pieces[0], accent_hex) if pieces else _full_bleed(None, accent_hex)
    _bottom_gradient(canvas, COVER_GRADIENT_H)
    return chapter_text(canvas, post)


def cinematic_cover(post: ListPost, pieces: list[Piece]) -> Image.Image:
    """The best piece in a wide band on black, between two accent lines."""
    accent = hex_to_rgb(readable_accent(post.accent))
    canvas = Image.new("RGBA", SIZE, (0, 0, 0, 255))
    if pieces:
        band = _crop_to(pieces[0], (SLIDE_W, CINEMA_H))
        canvas.paste(band.convert("RGBA"), (0, CINEMA_Y))
    draw = ImageDraw.Draw(canvas)
    for y in (CINEMA_Y - CINEMA_LINE - 8, CINEMA_Y + CINEMA_H + 8):
        draw.rectangle((0, y, SLIDE_W, y + CINEMA_LINE), fill=accent)
    return chapter_text(canvas, post)


def triptych_cover(post: ListPost, pieces: list[Piece]) -> Image.Image:
    """The three best pieces as tilted, white-framed strips over the best one's blur."""
    if not pieces:
        return focus_cover(post, pieces)
    canvas = _blurred(_crop(pieces[0]), SIZE, COVER_BLUR, COVER_DIM).convert("RGBA")
    for k, angle in enumerate(STRIP_TILT):
        strip = _framed(_crop_to(pieces[k % len(pieces)], STRIP), FRAME, angle)
        top = STRIP_TOP + k * STRIP_STEP - (strip.height - STRIP[1] - 2 * FRAME) // 2
        _paste_with_shadow(canvas, strip, (SLIDE_W - strip.width) // 2, top)
    _bottom_gradient(canvas, COVER_GRADIENT_H)
    return chapter_text(canvas, post)


def tease_cover(post: ListPost, pieces: list[Piece]) -> Image.Image:
    """The best piece blurred past recognition behind "CHAPTER" and its number, giant."""
    part = post.chapter
    accent_hex = readable_accent(post.accent)
    accent = hex_to_rgb(accent_hex)
    canvas = (
        _blurred(_crop(pieces[0]), SIZE, TEASE_BLUR, TEASE_DIM)
        if pieces
        else _accent_gradient(SIZE, accent_hex)
    ).convert("RGBA")
    _bottom_gradient(canvas, COVER_GRADIENT_H)
    layout = layout_tease(part.number)
    draw = ImageDraw.Draw(canvas)
    if layout.label:
        _draw_text(draw, layout.label, WHITE, WHITE)
    big = layout.number
    draw.text(
        (big.line_x(0), big.text.baselines(big.y)[0]),
        big.text.line_text(0),
        font=big.text.font,
        fill=accent,
        stroke_width=STROKE // 2,
        stroke_fill=DARK,
        anchor="ls",
    )
    # The number is up there already, so the pill only says which part this is.
    kicker = f"PART {part.part}/{part.parts}" if part.parts > 1 else "NEW CHAPTER"
    return chapter_text(canvas, post, kicker if part.number.strip() else chapter_kicker("", 1, 1))


def page_cover(post: ListPost, pieces: list[Piece], title_cover: Image.Image | None) -> Image.Image:
    """The best piece as a tilted, white-bordered page over the title's own cover blurred (the
    next piece's blur when the cover isn't at hand)."""
    accent_hex = readable_accent(post.accent)
    behind = title_cover or (_crop(pieces[1]) if len(pieces) > 1 else None)
    behind = behind or (_crop(pieces[0]) if pieces else None)
    canvas = (
        _blurred(behind, SIZE, COVER_BLUR, COVER_DIM) if behind else _accent_gradient(SIZE, accent_hex)
    ).convert("RGBA")
    if pieces:
        img, (left, top, right, bottom) = pieces[0]
        box = fit_inside(right - left, bottom - top, Box(0, 0, *PAGE_MAX))
        card = _framed(img.crop((left, top, right, bottom)).resize((box.w, box.h)), PAGE_BORDER, PAGE_TILT)
        y = max(120, PAGE_Y - card.height // 2)
        _paste_with_shadow(canvas, card, (SLIDE_W - card.width) // 2, y)
    _bottom_gradient(canvas, COVER_GRADIENT_H)
    return chapter_text(canvas, post)


def chapter_cover(
    style: ChapterCoverStyle,
    post: ListPost,
    pieces: list[Piece],
    title_cover: Image.Image | None,
) -> Image.Image:
    if style is ChapterCoverStyle.CINEMATIC:
        return cinematic_cover(post, pieces)
    if style is ChapterCoverStyle.TRIPTYCH:
        return triptych_cover(post, pieces)
    if style is ChapterCoverStyle.TEASE:
        return tease_cover(post, pieces)
    if style is ChapterCoverStyle.PAGE:
        return page_cover(post, pieces, title_cover)
    return focus_cover(post, pieces)

