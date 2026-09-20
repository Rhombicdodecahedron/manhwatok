"""Draws post slides (style C, blur-fill) as 1080×1920 PNGs with Pillow."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

from manhwatok.adapters.layout import (
    BAR_H,
    Box,
    PILL_BORDER,
    PILL_PAD_X,
    SLIDE_H,
    SLIDE_W,
    ItemLayout,
    Pill,
    Placed,
    fit_inside,
    byline_of,
    layout_chapter_cover,
    layout_cover,
    layout_end,
    layout_item,
)
from manhwatok.domain.color import hex_to_rgb, readable_accent
from manhwatok.domain.errors import StorageError
from manhwatok.domain.labels import chapter_label
from manhwatok.ports.posts import SlideArt
from manhwatok.domain.models import QUAD_PICTURES, ArtStyle, CoverStyle
from manhwatok.domain.post import ListPost

WHITE = (255, 255, 255)
DARK = (11, 11, 16)
DIM = (255, 255, 255, 77)
BYLINE = (255, 255, 255, 204)
SHADOW = (0, 0, 0, 190)
SIZE = (SLIDE_W, SLIDE_H)
# A cover behind its own card is blurred hard so the card reads; a banner is real art meant to
# be seen, so it keeps more detail and brightness.
COVER_BLUR, COVER_DIM = 36, 0.42
BANNER_BLUR, BANNER_DIM = 18, 0.50
# Where a panel crop takes its band from. A banner is already composed wide, so it crops from
# the middle; an upright cover's subject sits high, so its band is lifted off the centre.
BANNER_CROP, COVER_CROP = (0.5, 0.5), (0.5, 0.28)
# A scene fills the slide, so its crop takes the middle: pins are picked near 9:16 already,
# and there is no measured reason to bias one edge.
SCENE_CROP = (0.5, 0.5)
# The quad cover's tiles are portrait slices of mostly upright art whose faces sit high.
QUAD_CROP = (0.5, 0.2)
QUAD_COUNT = QUAD_PICTURES
QUARTER = (SLIDE_W // 2, SLIDE_H // 2)
MID_GREY = 110.0  # the brightness a drawn panel sits around, between black pages and blank ones


class _Art(NamedTuple):
    """One slide's images, opened. Only the ones the post's style needs are loaded."""

    cover: Image.Image | None
    banner: Image.Image | None
    character: Image.Image | None
    custom: Image.Image | None
    gallery: tuple[Image.Image, ...] = ()


GRADIENT_H = 920
# The scene style puts text on sharp, full-brightness art instead of a blurred backdrop, so
# its scrim has to start higher: the topmost rank number sits at y≈1228 with a two-line title
# and a three-line hook, and the curve only reaches 0.75 alpha there if it begins by y=615.
SCENE_GRADIENT_H = 1320


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


def _filled(src: Image.Image, area: Box, centering: tuple[float, float]) -> Image.Image:
    """`src` cropped to fill `area` exactly, as a rounded card."""
    return _rounded(
        ImageOps.fit(src, (area.w, area.h), Image.Resampling.LANCZOS, centering=centering), 24
    )


def _backdrop(
    banner: Image.Image | None, cover: Image.Image | None, accent: str
) -> Image.Image:
    """What fills a manhwa slide behind the card: the banner when the post asks for one and the
    title has it, else the blurred cover, else a plain accent gradient."""
    if banner:
        return _blurred(banner, SIZE, BANNER_BLUR, BANNER_DIM)
    if cover:
        return _blurred(cover, SIZE, COVER_BLUR, COVER_DIM)
    return _accent_gradient(SIZE, accent)


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


def _full_bleed(src: Image.Image | None, accent: str) -> Image.Image:
    """`src` cropped to fill the whole slide, square-cornered; the accent gradient without one."""
    canvas = _accent_gradient(SIZE, accent).convert("RGBA")
    if src:
        filled = ImageOps.fit(src, SIZE, Image.Resampling.LANCZOS, centering=SCENE_CROP)
        canvas.paste(filled.convert("RGBA"), (0, 0))
    return canvas


def _backdrop_panel(panels: list[Image.Image | None]) -> Image.Image | None:
    """Which panel the cover is built on. A chapter often opens on a black page or a blank one,
    and blurring either gives a cover with nothing on it — so this takes the panel closest to
    mid-brightness, which is a drawn one."""
    lit = [(abs(_brightness(p) - MID_GREY), n, p) for n, p in enumerate(panels) if p is not None]
    return min(lit)[2] if lit else None


def _brightness(img: Image.Image) -> float:
    small = img.convert("L").resize((8, 8), Image.Resampling.BOX)
    data = small.tobytes()
    return sum(data) / len(data)


def _grid(pictures: list[Image.Image], accent: str) -> Image.Image:
    """`pictures` 2×2 over the whole slide, square-cornered and edge to edge, repeated in order
    when there are fewer than four; the accent gradient when there are none."""
    if not pictures:
        return _accent_gradient(SIZE, accent).convert("RGBA")
    canvas = Image.new("RGBA", SIZE)
    for k in range(QUAD_COUNT):
        tile = ImageOps.fit(
            pictures[k % len(pictures)], QUARTER, Image.Resampling.LANCZOS, centering=QUAD_CROP
        )
        canvas.paste(tile.convert("RGBA"), ((k % 2) * QUARTER[0], (k // 2) * QUARTER[1]))
    return canvas


def _save(slide: Image.Image, path: Path) -> None:
    try:
        slide.convert("RGB").save(path)
    except OSError as e:
        raise StorageError(f"could not save slide {path}: {e}") from e


def _bottom_gradient(canvas: Image.Image, height: int = GRADIENT_H) -> None:
    """Darken the lowest `height` px: transparent → 88% black at 55% → black."""
    alpha = []
    for y in range(height):
        t = y / (height - 1)
        a = 0.88 * t / 0.55 if t <= 0.55 else 0.88 + 0.12 * (t - 0.55) / 0.45
        alpha.append(round(255 * a))
    mask = Image.new("L", (1, height))
    mask.putdata(alpha)
    mask = mask.resize((SLIDE_W, height))
    canvas.paste((0, 0, 0), (0, SLIDE_H - height, SLIDE_W, SLIDE_H), mask)


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


def _byline(post: ListPost) -> str:
    """Who the post is by, for the mark every slide carries; nothing without an account."""
    return f"by @{post.account}" if post.account else ""


def _draw_byline(canvas: Image.Image, placed: Placed | None) -> None:
    """The byline, slightly faded, over a soft shadow — it sits on art of any brightness."""
    if placed is None:
        return
    layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    shadow = ImageDraw.Draw(layer)
    _draw_text(shadow, Placed(placed.text, placed.x + 2, placed.y + 2, placed.w), SHADOW, SHADOW)
    layer = layer.filter(ImageFilter.GaussianBlur(3))
    _draw_text(ImageDraw.Draw(layer), placed, BYLINE, BYLINE)
    canvas.alpha_composite(layer)


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
    def render(self, post: ListPost, art: dict[int, SlideArt], out_dir: Path) -> list[Path]:
        """Write 01.png (cover) … NN.png (end slide) into out_dir, replacing old slides, plus
        every cover version as cover-<style>.png; the post's chosen one is also 01.png."""
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            for old in [*out_dir.glob("[0-9][0-9].png"), *out_dir.glob("cover-*.png")]:
                old.unlink()
        except OSError as e:
            raise StorageError(f"could not prepare slide folder {out_dir}: {e}") from e
        if post.chapter is not None:
            return self._render_chapter(post, out_dir)
        wants_banner = post.art in (ArtStyle.BACKGROUND, ArtStyle.PANEL)
        # The quad cover draws the first four titles' characters whatever the post's style.
        quad_ids = {it.manhwa.anilist_id for it in post.items[:QUAD_COUNT]}
        loaded = {
            m_id: _Art(
                _load(one.cover),
                _load(one.banner) if wants_banner else None,
                _load(one.character)
                if post.art is ArtStyle.CHARACTER or m_id in quad_ids
                else None,
                _load(one.custom),
                tuple(
                    img
                    for img in (_load(p) for p in one.gallery[:QUAD_COUNT])
                    if img is not None
                )
                if post.art is ArtStyle.QUAD
                else (),
            )
            for m_id, one in art.items()
        }
        covers = {m_id: one.cover for m_id, one in loaded.items()}
        versions = {style: self.cover_slide(post, loaded, style) for style in CoverStyle}
        slides = [versions[post.cover]]
        slides += [self.item_slide(post, i, loaded) for i in range(len(post.items))]
        slides.append(self.end_slide(post, covers))
        paths = []
        for n, slide in enumerate(slides, 1):
            path = out_dir / f"{n:02d}.png"
            _save(slide, path)
            paths.append(path)
        for style, slide in versions.items():
            _save(slide, out_dir / f"cover-{style.value}.png")
        return paths

    def _render_chapter(self, post: ListPost, out_dir: Path) -> list[Path]:
        """A chapter post: the cover, one slide per panel, the end slide. A chapter has one
        sensible cover, so the other versions are not drawn."""
        panels = [_load(out_dir / name) for name in post.chapter.panels]
        slides = [self.chapter_cover_slide(post, _backdrop_panel(panels))]
        slides += [self.panel_slide(post, panel) for panel in panels]
        slides.append(self.chapter_end_slide(post, panels[-1] if panels else None))
        paths = []
        for n, slide in enumerate(slides, 1):
            path = out_dir / f"{n:02d}.png"
            _save(slide, path)
            paths.append(path)
        _save(slides[0], out_dir / f"cover-{CoverStyle.FAN.value}.png")
        return paths

    def panel_slide(self, post: ListPost, panel: Image.Image | None) -> Image.Image:
        """The panel, and the mark every slide carries. The cutter already made it slide-sized;
        anything else — a panel from elsewhere, or a file that has gone — is fitted."""
        accent = readable_accent(post.accent)
        canvas = _full_bleed(panel, accent) if panel else _accent_gradient(SIZE, accent).convert("RGBA")
        _draw_byline(canvas, byline_of(_byline(post)))
        return canvas

    def chapter_cover_slide(self, post: ListPost, first: Image.Image | None) -> Image.Image:
        """The chapter's first panel, blurred, under the chapter's name and its part bar."""
        part = post.chapter
        accent_hex = readable_accent(post.accent)
        accent = hex_to_rgb(accent_hex)
        canvas = (
            _blurred(first, SIZE, COVER_BLUR, COVER_DIM)
            if first
            else _accent_gradient(SIZE, accent_hex)
        ).convert("RGBA")
        _bottom_gradient(canvas)
        layout = layout_chapter_cover(
            part.manhwa_title, part.number, part.part, part.parts, _byline(post)
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

    def chapter_end_slide(self, post: ListPost, last: Image.Image | None) -> Image.Image:
        """The last panel, blurred, under the account's own closing words."""
        part = post.chapter
        accent_hex = readable_accent(post.accent)
        accent = hex_to_rgb(accent_hex)
        canvas = (
            _blurred(last, SIZE, COVER_BLUR, COVER_DIM)
            if last
            else _accent_gradient(SIZE, accent_hex)
        ).convert("RGBA")
        name = f"{part.manhwa_title} — ch. {part.number}" if part.number else part.manhwa_title
        layout = layout_end([name], post.cta_title, post.cta_follow, _byline(post))
        draw = ImageDraw.Draw(canvas)
        _draw_text(draw, layout.title, WHITE, accent)
        for row in layout.rows:
            if row.number:
                _draw_text(draw, row.number, accent, accent)
            _draw_text(draw, row.name, WHITE, accent)
        _draw_text(draw, layout.follow, WHITE, accent)
        _draw_byline(canvas, layout.byline)
        return canvas

    def item_slide(self, post: ListPost, index: int, loaded: dict[int, _Art]) -> Image.Image:
        item = post.items[index]
        m = item.manhwa
        accent_hex = readable_accent(m.cover_color, post.accent)
        accent = hex_to_rgb(accent_hex)
        art = loaded.get(m.anilist_id) or _Art(None, None, None, None)
        img, banner = art.cover, art.banner
        layout = layout_item(
            index + 1, m.title, chapter_label(m), item.hook, art=post.art, byline=_byline(post)
        )
        area = layout.cover_area
        if post.art is ArtStyle.SCENE:
            # One picture, the whole slide, square-cornered: no card, so no backdrop behind it,
            # no rounding and no shadow. Art the user picked by hand is the point of the style;
            # the cover stands in, cropped to the same shape, so a title without one still fills
            # the screen rather than dropping out of the post's rhythm.
            canvas = _full_bleed(art.custom or img, accent_hex)
            _bottom_gradient(canvas, SCENE_GRADIENT_H)
            return self._item_text(canvas, layout, accent)
        if post.art is ArtStyle.QUAD:
            # Four of the title's own pictures, edge to edge: its characters, picked art and
            # scenes, topped up with the cover and repeated when it has fewer.
            pictures = list(art.gallery)
            if len(pictures) < QUAD_COUNT and img is not None:
                pictures.append(img)
            canvas = _grid(pictures, accent_hex)
            _bottom_gradient(canvas, SCENE_GRADIENT_H)
            return self._item_text(canvas, layout, accent)
        canvas = _backdrop(banner, img, accent_hex).convert("RGBA")
        if post.art is ArtStyle.PANEL:
            # The banner is the point of this style; the cover stands in, cropped to the same
            # shape, so a title without a banner doesn't break the post's rhythm. Art the user
            # picked by hand beats both, and is framed like a cover since it could be anything.
            src = art.custom or banner or img or _accent_gradient((area.w, area.h), accent_hex)
            crop = BANNER_CROP if banner and not art.custom else COVER_CROP
            box, card = area, _filled(src, area, crop)
        else:
            # Hand-picked art first, then the character portrait when this style has one, then
            # the cover. All are fitted, never cropped: the art is already framed tightly on its
            # subject, and the bigger box is there to show more of it, not less.
            src = art.custom or art.character or img or _accent_gradient((460, 650), accent_hex)
            box = fit_inside(src.width, src.height, area)
            card = _rounded(src.resize((box.w, box.h), Image.Resampling.LANCZOS), 24)
        _paste_with_shadow(canvas, card, box.x, box.y)
        _bottom_gradient(canvas)
        return self._item_text(canvas, layout, accent)

    @staticmethod
    def _item_text(
        canvas: Image.Image, layout: ItemLayout, accent: tuple[int, int, int]
    ) -> Image.Image:
        """The text stack every style shares: it sits in the same place whatever the art does."""
        draw = ImageDraw.Draw(canvas)
        _draw_text(draw, layout.rank, accent, accent)
        _draw_text(draw, layout.name, WHITE, accent)
        _draw_pill(draw, layout.pill, accent, filled=False)
        if layout.hook:
            _draw_text(draw, layout.hook, WHITE, accent)
        _draw_byline(canvas, layout.byline)
        return canvas

    def cover_slide(
        self, post: ListPost, loaded: dict[int, _Art], style: CoverStyle = CoverStyle.FAN
    ) -> Image.Image:
        if style is CoverStyle.QUAD:
            canvas = self._quad_art(post, loaded)
        elif style is CoverStyle.HERO:
            canvas = self._hero_art(post, loaded)
        else:
            canvas = self._fan_art(post, loaded)
        return self._cover_text(canvas, post)

    @staticmethod
    def _fan_art(post: ListPost, loaded: dict[int, _Art]) -> Image.Image:
        """The first three covers fanned out over the first one's blur."""
        images = {m_id: one.cover for m_id, one in loaded.items()}
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
        return canvas

    @staticmethod
    def _quad_art(post: ListPost, loaded: dict[int, _Art]) -> Image.Image:
        """The first four titles' characters, one per quadrant, edge to edge. A title without a
        portrait gives its picked art or its cover instead; fewer than four titles repeat."""
        tiles = []
        for it in post.items[:QUAD_COUNT]:
            m = it.manhwa
            art = loaded.get(m.anilist_id) or _Art(None, None, None, None)
            tiles.append(
                art.character
                or art.custom
                or art.cover
                or _accent_gradient(QUARTER, readable_accent(m.cover_color, post.accent))
            )
        canvas = _grid(tiles, readable_accent(post.accent))
        _bottom_gradient(canvas, SCENE_GRADIENT_H)
        return canvas

    @staticmethod
    def _hero_art(post: ListPost, loaded: dict[int, _Art]) -> Image.Image:
        """The first title's picked art, else its cover, filling the whole slide."""
        m = post.items[0].manhwa
        art = loaded.get(m.anilist_id) or _Art(None, None, None, None)
        canvas = _full_bleed(art.custom or art.cover, readable_accent(m.cover_color, post.accent))
        _bottom_gradient(canvas, SCENE_GRADIENT_H)
        return canvas

    @staticmethod
    def _cover_text(canvas: Image.Image, post: ListPost) -> Image.Image:
        """The text every cover version shares: pill, title, progress bar and byline."""
        accent = hex_to_rgb(readable_accent(post.accent))
        layout = layout_cover(post.title, len(post.items), _byline(post))
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
        _draw_byline(canvas, layout.byline)
        return canvas

    def end_slide(self, post: ListPost, images: dict[int, Image.Image | None]) -> Image.Image:
        accent = hex_to_rgb(readable_accent(post.accent))
        tiles = [images.get(it.manhwa.anilist_id) for it in post.items[:4]]
        tiles = [t for t in tiles if t is not None]
        if tiles:
            # 2×2 grid of sharp covers, blurred once as a whole so there are no seams
            half = (SLIDE_W // 2, SLIDE_H // 2)
            grid = Image.new("RGB", SIZE)
            for k in range(4):
                tile = ImageOps.fit(tiles[k % len(tiles)], half, Image.Resampling.LANCZOS)
                grid.paste(tile, ((k % 2) * half[0], (k // 2) * half[1]))
            canvas = _blurred(grid, SIZE, 30, 0.30).convert("RGBA")
        else:
            canvas = _accent_gradient(SIZE, readable_accent(post.accent)).convert("RGBA")
        layout = layout_end(
            [it.manhwa.title for it in post.items],
            post.cta_title,
            post.cta_follow,
            _byline(post),
        )
        draw = ImageDraw.Draw(canvas)
        _draw_text(draw, layout.title, WHITE, accent)
        for i, row in enumerate(layout.rows):
            if row.number:
                item = post.items[i].manhwa
                num_color = hex_to_rgb(readable_accent(item.cover_color, post.accent))
                _draw_text(draw, row.number, num_color, num_color)
            _draw_text(draw, row.name, WHITE, accent)
        _draw_text(draw, layout.follow, WHITE, accent)
        _draw_byline(canvas, layout.byline)
        return canvas
