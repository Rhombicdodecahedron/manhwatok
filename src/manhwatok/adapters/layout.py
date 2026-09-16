"""Pure slide layout: fit text into boxes and stack it inside the TikTok safe area.

Nothing here draws. Every function returns positions (in 1080×1920 slide pixels) so the
renderer can paint them and tests can check that everything stays inside SAFE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from PIL.ImageFont import FreeTypeFont

from manhwatok.adapters.fonts import body, bold, display
from manhwatok.domain.text import accent_spans

SLIDE_W, SLIDE_H = 1080, 1920
GAP = 24
PILL_PAD_X, PILL_PAD_Y, PILL_BORDER = 28, 16, 6

Run = tuple[str, bool]  # (text, accent)
Word = tuple[Run, ...]  # one or more runs, concatenated with no space, forming one word
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
    """Split the spans' JOINED text on whitespace, so a span boundary without whitespace (e.g.
    an accent run ending mid-word, or right before punctuation) stays inside one word — as
    several runs — instead of becoming a stray word break."""
    words: list[Word] = []
    current: list[list] = []  # [[run_text, accent], ...] runs of the word being built

    def flush() -> None:
        if current:
            words.append(tuple((t, a) for t, a in current))
            current.clear()

    for text, accent in spans:
        i, n = 0, len(text)
        while i < n:
            if text[i].isspace():
                flush()
                i += 1
                continue
            j = i
            while j < n and not text[j].isspace():
                j += 1
            piece = text[i:j]
            if current and current[-1][1] == accent:
                current[-1][0] += piece
            else:
                current.append([piece, accent])
            i = j
    flush()
    return words


def plain_words(text: str) -> list[Word]:
    return [((w, False),) for w in text.split()]


def word_text(word: Word) -> str:
    return "".join(t for t, _ in word)


def _join(words: list[Word] | tuple[Word, ...]) -> str:
    return " ".join(word_text(w) for w in words)


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
    """Split an over-wide word into pieces that each fit max_width, keeping each piece's
    characters' original accent runs (a piece may itself carry more than one run)."""
    if font.getlength(word_text(word)) <= max_width:
        return [word]
    pieces: list[Word] = []
    current: list[list] = []

    def flush() -> None:
        if current:
            pieces.append(tuple((t, a) for t, a in current))
            current.clear()

    for text, accent in word:
        for ch in text:
            trial = "".join(t for t, _ in current) + ch
            if current and font.getlength(trial) > max_width:
                flush()
                current.append([ch, accent])
            elif current and current[-1][1] == accent:
                current[-1][0] += ch
            else:
                current.append([ch, accent])
    flush()
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
        last = list(words[-1])  # runs of the last word, as mutable [text, accent] pairs
        text, accent = last[-1]
        candidate_last = tuple(last[:-1] + [(text + "…", accent)])
        candidate = words[:-1] + [candidate_last]
        if font.getlength(_join(candidate)) <= max_width:
            return candidate
        trimmed = text[:-1].rstrip()
        if trimmed:
            last[-1] = (trimmed, accent)
            words[-1] = tuple(last)
        elif len(last) > 1:
            last.pop()
            words[-1] = tuple(last)
        else:
            words.pop()
    return [(("…", False),)]


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
# The panel style's image box: the full safe width, in a cinematic ratio. A banner is ~4.75:1
# and a cover ~0.7:1, so whichever one fills it is cropped — the box's shape is what makes
# every slide in a panel post match.
PANEL_RATIO = 2.1


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


def layout_item(
    rank: int, name: str, pill_label: str, hook: str, panel: bool = False
) -> ItemLayout:
    x = SAFE.x
    rank_t = fit_words(plain_words(f"#{rank}"), display, ITEM_TEXT_W, 1, 96, 96)
    name_t = fit_words(plain_words(name.upper() or "?"), display, ITEM_TEXT_W, 2, 62, 42, 1.08)
    pill = make_pill(pill_label.upper(), bold, 32, ITEM_TEXT_W, x)
    hook_t = (
        fit_words(plain_words(hook), body, ITEM_TEXT_W, 3, 36, 28, 1.34)
        if hook.strip()
        else None
    )
    heights = [rank_t.height, name_t.height, pill.box.h] + ([hook_t.height] if hook_t else [])
    tops = stack_up(heights, SAFE.bottom)
    cover_bottom = tops[0] - 40
    free_h = cover_bottom - SAFE.y
    if panel:
        area = _panel_area(free_h, cover_bottom)
    else:
        area = Box((SLIDE_W - COVER_MAX_W) // 2, SAFE.y, COVER_MAX_W, max(1, min(COVER_MAX_H, free_h)))
    return ItemLayout(
        rank=Placed(rank_t, x, tops[0], ITEM_TEXT_W),
        name=Placed(name_t, x, tops[1], ITEM_TEXT_W),
        pill=_at(pill, tops[2]),
        hook=Placed(hook_t, x, tops[3], ITEM_TEXT_W) if hook_t else None,
        cover_area=area,
    )


def _panel_area(free_h: int, free_bottom: int) -> Box:
    """A landscape box the full safe width, centred in the space left above the text. Shrinks
    to fit when a long title and hook leave less room than the ratio wants."""
    h = max(1, min(round(SAFE.w / PANEL_RATIO), free_h))
    return Box(SAFE.x, SAFE.y + (free_h - h) // 2, SAFE.w, h)


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
    kicker = make_pill(f"{count} PICK" if count == 1 else f"{count} PICKS", bold, 32, w, x)
    title_t = fit_words(words_of(accent_spans(title.upper())), display, w, 4, 92, 56, 1.06)
    tops = stack_up([kicker.box.h, title_t.height, BAR_H], SAFE.bottom)
    seg_w = (w - BAR_GAP * (count - 1)) / max(count, 1)
    bar = [
        Box(round(x + i * (seg_w + BAR_GAP)), tops[2], max(1, round(seg_w)), BAR_H)
        for i in range(count)
    ]
    return CoverLayout(_at(kicker, tops[0]), Placed(title_t, x, tops[1], w), bar)


# --- end slide ----------------------------------------------------------------------------

END_TITLE_TOP, FOLLOW_BOTTOM = 480, 1560
LIST_X, LIST_RIGHT = 130, 960
LIST_GAP = 56  # clear space between the recap band and the title / the follow line
LIST_MAX, LIST_MIN, LIST_SHRINK_FLOOR = 44, 28, 34  # recap text sizes
ROW_PITCH = 1.9  # row height / text size


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


def _num_col(size: int, count: int) -> int:
    """Width of the rank-number column: the widest number plus a gap."""
    return math.ceil(display(size).getlength(str(count))) + 24


def _list_size(names: list[str], avail: int) -> int:
    """Largest recap size whose rows fit `avail` and whose longest name fits one line; below
    LIST_SHRINK_FLOOR names are ellipsized instead of shrinking the whole list further."""
    for s in range(LIST_MAX, LIST_MIN - 1, -2):
        if round(s * ROW_PITCH) * len(names) > avail:
            continue
        widest = max((body(s).getlength(n) for n in names), default=0)
        if s <= LIST_SHRINK_FLOOR or widest <= LIST_RIGHT - LIST_X - _num_col(s, len(names)):
            return s
    return LIST_MIN


def _recap_rows(
    shown: list[tuple[str | None, str]], size: int, count: int, top: int
) -> list[EndRow]:
    num_col = _num_col(size, count)
    name_w = LIST_RIGHT - LIST_X - num_col
    pitch = round(size * ROW_PITCH)
    rows: list[EndRow] = []
    for i, (num, name) in enumerate(shown):
        name_t = fit_words(plain_words(name), body, name_w, 1, size, size)
        num_t = fit_words(plain_words(num), display, num_col, 1, size, size) if num else None
        # shared baseline so the Black-weight number and the name sit on one line
        ascent = max(-name_t.ink_top, -(num_t.ink_top if num_t else 0))
        baseline = top + i * pitch + ascent
        rows.append(
            EndRow(
                Placed(num_t, LIST_X, baseline + num_t.ink_top, num_col) if num_t else None,
                Placed(name_t, LIST_X + num_col, baseline + name_t.ink_top, name_w),
            )
        )
    return rows


def _ink_span(rows: list[EndRow]) -> tuple[int, int]:
    boxes = [b for r in rows for b in ([r.number.box] if r.number else []) + [r.name.box]]
    return min(b.y for b in boxes), max(b.bottom for b in boxes)


def layout_end(names: list[str], cta_title: str, cta_follow: str) -> EndLayout:
    """Title near the top, follow line near the bottom, and the numbered recap centred
    vertically in the band between them (a long list fills it and ends in "+N more")."""
    x, w = SAFE.x, SAFE.w
    title_t = fit_words(words_of(accent_spans(cta_title.upper())), display, w, 3, 100, 68, 1.06)
    title = Placed(title_t, x, END_TITLE_TOP, w, "center")
    follow_t = fit_words(plain_words(cta_follow.upper()), bold, w, 2, 44, 32, 1.2)
    follow = Placed(follow_t, x, FOLLOW_BOTTOM - follow_t.height, w, "center")

    band_top = title.box.bottom + LIST_GAP
    band_bottom = follow.box.y - LIST_GAP
    avail = band_bottom - band_top
    size = _list_size(names, avail)
    max_rows = max(1, avail // round(size * ROW_PITCH))
    shown: list[tuple[str | None, str]] = [(str(i), n) for i, n in enumerate(names, 1)]
    if len(shown) > max_rows:
        rest = len(shown) - (max_rows - 1)
        shown = shown[: max_rows - 1] + [(None, f"+{rest} more")]

    ink_top, ink_bottom = _ink_span(_recap_rows(shown, size, len(names), 0))
    top = band_top + (avail - (ink_bottom - ink_top)) // 2 - ink_top
    return EndLayout(title, _recap_rows(shown, size, len(names), top), follow)
