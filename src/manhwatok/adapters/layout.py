"""Pure slide layout: fit text into boxes and stack it inside the TikTok safe area.

Nothing here draws. Every function returns positions (in 1080×1920 slide pixels) so the
renderer can paint them and tests can check that everything stays inside SAFE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from PIL.ImageFont import FreeTypeFont

from manhwatok.adapters.fonts import anton, inter_extrabold, inter_semibold
from manhwatok.domain.text import accent_spans

SLIDE_W, SLIDE_H = 1080, 1920
GAP = 24
PILL_PAD_X, PILL_PAD_Y, PILL_BORDER = 28, 16, 6
END_TITLE = "Which one have you *read?*"
FOLLOW = "Follow for part 2"

Word = tuple[str, bool]  # (text, accent)
FontFor = Callable[[int], FreeTypeFont]


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def contains(self, other: Box) -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and other.right <= self.right
            and other.bottom <= self.bottom
        )


SAFE = Box(90, 250, 900, 1420)  # x 90–990, y 250–1670


def words_of(spans: list[tuple[str, bool]]) -> list[Word]:
    return [(w, accent) for text, accent in spans for w in text.split()]


def plain_words(text: str) -> list[Word]:
    return [(w, False) for w in text.split()]


def _join(words: list[Word] | tuple[Word, ...]) -> str:
    return " ".join(w for w, _ in words)


@dataclass(frozen=True)
class FittedText:
    lines: tuple[tuple[Word, ...], ...]
    font: FreeTypeFont
    line_height: int

    def line_text(self, i: int) -> str:
        return _join(self.lines[i])

    def line_width(self, i: int) -> int:
        return math.ceil(self.font.getlength(self.line_text(i)))

    @property
    def width(self) -> int:
        return max((self.line_width(i) for i in range(len(self.lines))), default=0)

    @property
    def ink_top(self) -> int:
        """Offset from the first baseline up to the top of the ink (negative)."""
        return self.font.getbbox(self.line_text(0), anchor="ls")[1] if self.lines else 0

    @property
    def ink_bottom(self) -> int:
        """Offset from the last baseline down to the bottom of the ink."""
        return (
            self.font.getbbox(self.line_text(len(self.lines) - 1), anchor="ls")[3]
            if self.lines
            else 0
        )

    @property
    def height(self) -> int:
        if not self.lines:
            return 0
        return (len(self.lines) - 1) * self.line_height + self.ink_bottom - self.ink_top

    def baselines(self, top: int) -> list[int]:
        first = top - self.ink_top
        return [first + i * self.line_height for i in range(len(self.lines))]


def _break_word(word: Word, font: FreeTypeFont, max_width: int) -> list[Word]:
    text, accent = word
    if font.getlength(text) <= max_width:
        return [word]
    pieces, current = [], ""
    for ch in text:
        if current and font.getlength(current + ch) > max_width:
            pieces.append((current, accent))
            current = ch
        else:
            current += ch
    if current:
        pieces.append((current, accent))
    return pieces


def wrap_words(words: list[Word], font: FreeTypeFont, max_width: int) -> list[list[Word]]:
    lines: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        for piece in _break_word(word, font, max_width):
            if current and font.getlength(_join(current + [piece])) > max_width:
                lines.append(current)
                current = [piece]
            else:
                current = current + [piece]
    if current:
        lines.append(current)
    return lines


def _ellipsize(line: list[Word], font: FreeTypeFont, max_width: int) -> list[Word]:
    words = list(line)
    while words:
        text, accent = words[-1]
        candidate = words[:-1] + [(text + "…", accent)]
        if font.getlength(_join(candidate)) <= max_width:
            return candidate
        trimmed = text[:-1].rstrip()
        if trimmed:
            words[-1] = (trimmed, accent)
        else:
            words.pop()
    return [("…", False)]


def fit_words(
    words: list[Word],
    font_for: FontFor,
    max_width: int,
    max_lines: int,
    size: int,
    min_size: int,
    line_spacing: float = 1.05,
) -> FittedText:
    """Largest size (step 4, down to min_size) whose wrap fits max_lines; else ellipsize at min_size."""
    s = size
    while True:
        font = font_for(s)
        lines = wrap_words(words, font, max_width)
        if len(lines) <= max_lines or s <= min_size:
            break
        s = max(min_size, s - 4)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(lines[-1], font, max_width)
    return FittedText(tuple(tuple(line) for line in lines), font, round(s * line_spacing))


def stack_up(heights: list[int], bottom: int, gap: int = GAP) -> list[int]:
    """Top y of each block when stacked upward so the last block ends at `bottom`."""
    tops: list[int] = []
    y = bottom
    for h in reversed(heights):
        y -= h
        tops.append(y)
        y -= gap
    return list(reversed(tops))


@dataclass(frozen=True)
class Placed:
    text: FittedText
    x: int
    y: int  # top of the ink
    w: int  # region width; lines are left-aligned or centred inside it
    align: str = "left"

    @property
    def box(self) -> Box:
        return Box(self.x, self.y, self.w, self.text.height)

    def line_x(self, i: int) -> int:
        if self.align == "center":
            return self.x + (self.w - self.text.line_width(i)) // 2
        return self.x


@dataclass(frozen=True)
class Pill:
    text: FittedText
    box: Box  # outer box incl. padding and border

    @property
    def text_top(self) -> int:
        return self.box.y + PILL_PAD_Y


def make_pill(label: str, font_for: FontFor, size: int, max_width: int, x: int, y: int = 0) -> Pill:
    text = fit_words(
        plain_words(label), font_for, max_width - 2 * PILL_PAD_X, 1, size, size - 8, 1.0
    )
    return Pill(text, Box(x, y, text.width + 2 * PILL_PAD_X, text.height + 2 * PILL_PAD_Y))


def _at(pill: Pill, y: int) -> Pill:
    return Pill(pill.text, Box(pill.box.x, y, pill.box.w, pill.box.h))


def fit_inside(img_w: int, img_h: int, area: Box) -> Box:
    """Largest box with the image's aspect inside `area`, centred horizontally, top-aligned."""
    scale = min(area.w / img_w, area.h / img_h)
    w, h = max(1, round(img_w * scale)), max(1, round(img_h * scale))
    return Box(area.x + (area.w - w) // 2, area.y, w, h)


# --- manhwa slide -------------------------------------------------------------------------

ITEM_TEXT_W = 870  # x 90–960 (keeps clear of TikTok's right-hand buttons)
COVER_MAX_W, COVER_MAX_H = 620, 876


@dataclass(frozen=True)
class ItemLayout:
    rank: Placed
    name: Placed
    pill: Pill
    hook: Placed | None
    cover_area: Box  # the sharp cover is fitted inside this box

    def text_boxes(self) -> list[Box]:
        boxes = [self.rank.box, self.name.box, self.pill.box]
        return boxes + ([self.hook.box] if self.hook else [])


def layout_item(rank: int, name: str, pill_label: str, hook: str) -> ItemLayout:
    x = SAFE.x
    rank_t = fit_words(plain_words(f"#{rank}"), anton, ITEM_TEXT_W, 1, 120, 120)
    name_t = fit_words(plain_words(name.upper() or "?"), anton, ITEM_TEXT_W, 2, 84, 56, 1.04)
    pill = make_pill(pill_label.upper(), inter_extrabold, 36, ITEM_TEXT_W, x)
    hook_t = (
        fit_words(plain_words(hook), inter_semibold, ITEM_TEXT_W, 3, 40, 32, 1.32)
        if hook.strip()
        else None
    )
    heights = [rank_t.height, name_t.height, pill.box.h] + ([hook_t.height] if hook_t else [])
    tops = stack_up(heights, SAFE.bottom)
    cover_bottom = tops[0] - 40
    area_h = max(1, min(COVER_MAX_H, cover_bottom - SAFE.y))
    return ItemLayout(
        rank=Placed(rank_t, x, tops[0], ITEM_TEXT_W),
        name=Placed(name_t, x, tops[1], ITEM_TEXT_W),
        pill=_at(pill, tops[2]),
        hook=Placed(hook_t, x, tops[3], ITEM_TEXT_W) if hook_t else None,
        cover_area=Box((SLIDE_W - COVER_MAX_W) // 2, SAFE.y, COVER_MAX_W, area_h),
    )


# --- cover slide --------------------------------------------------------------------------

BAR_H, BAR_GAP = 16, 20


@dataclass(frozen=True)
class CoverLayout:
    kicker: Pill
    title: Placed
    bar: list[Box]

    def text_boxes(self) -> list[Box]:
        return [self.kicker.box, self.title.box, *self.bar]


def layout_cover(title: str, count: int) -> CoverLayout:
    x, w = SAFE.x, SAFE.w
    kicker = make_pill(f"{count} PICKS", inter_extrabold, 36, w, x)
    title_t = fit_words(words_of(accent_spans(title.upper())), anton, w, 4, 124, 72, 1.02)
    tops = stack_up([kicker.box.h, title_t.height, BAR_H], SAFE.bottom)
    seg_w = (w - BAR_GAP * (count - 1)) / max(count, 1)
    bar = [
        Box(round(x + i * (seg_w + BAR_GAP)), tops[2], max(1, round(seg_w)), BAR_H)
        for i in range(count)
    ]
    return CoverLayout(_at(kicker, tops[0]), Placed(title_t, x, tops[1], w), bar)


# --- end slide ----------------------------------------------------------------------------

LIST_X, LIST_RIGHT, LIST_BOTTOM = 160, 920, 1460
FOLLOW_BOTTOM = 1560


@dataclass(frozen=True)
class EndRow:
    number: Placed | None
    name: Placed


@dataclass(frozen=True)
class EndLayout:
    title: Placed
    rows: list[EndRow]
    follow: Placed

    def text_boxes(self) -> list[Box]:
        boxes = [self.title.box, self.follow.box]
        for row in self.rows:
            boxes += ([row.number.box] if row.number else []) + [row.name.box]
        return boxes


def layout_end(names: list[str]) -> EndLayout:
    x, w = SAFE.x, SAFE.w
    title_t = fit_words(words_of(accent_spans(END_TITLE.upper())), anton, w, 3, 136, 96, 1.02)
    title = Placed(title_t, x, 480, w, "center")
    follow_t = fit_words(plain_words(FOLLOW.upper()), inter_extrabold, w, 1, 48, 48)
    follow = Placed(follow_t, x, FOLLOW_BOTTOM - follow_t.height, w, "center")

    top = title.box.bottom + 40
    avail = LIST_BOTTOM - top
    size = 28
    for s in range(44, 27, -2):
        if round(s * 1.9) * len(names) <= avail:
            size = s
            break
    pitch = round(size * 1.9)
    max_rows = max(1, avail // pitch)
    shown: list[tuple[str | None, str]] = [(str(i), n) for i, n in enumerate(names, 1)]
    if len(shown) > max_rows:
        rest = len(shown) - (max_rows - 1)
        shown = shown[: max_rows - 1] + [(None, f"+{rest} more")]

    num_font = anton(size)
    num_col = math.ceil(num_font.getlength(str(len(names)))) + 24
    name_w = LIST_RIGHT - LIST_X - num_col
    rows: list[EndRow] = []
    for i, (num, name) in enumerate(shown):
        name_t = fit_words(plain_words(name), inter_semibold, name_w, 1, size, size)
        num_t = fit_words(plain_words(num), anton, num_col, 1, size, size) if num else None
        # shared baseline so the Anton number and Inter name sit on one line
        ascent = max(-name_t.ink_top, -(num_t.ink_top if num_t else 0))
        baseline = top + i * pitch + ascent
        rows.append(
            EndRow(
                Placed(num_t, LIST_X, baseline + num_t.ink_top, num_col) if num_t else None,
                Placed(name_t, LIST_X + num_col, baseline + name_t.ink_top, name_w),
            )
        )
    return EndLayout(title, rows, follow)
