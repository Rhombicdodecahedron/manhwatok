"""Where a piece of a chapter stops being the story: scanlator credits, a website banner, an ad
for a Discord, the title card.

A chapter opens and closes on these, and on a slideshow they are wasted slides (a competitor's
website, worse). They are told apart by what is written on them, read with RapidOCR offline:
a website address or scanlation words (translator, editor, discord, "read at", "Art:"...), the
manhwa's own name, or "To be continued" with the end card under it. One scanlation line on busy
art is a watermark over a story panel and stays; on a mostly empty stretch, or two of them
anywhere, it is junk. The title and the end only count on a mostly empty stretch, so a character
saying the name in a bubble stays in. The last story panel often shares its slide with the
credits, so what is found is the row the junk starts at: the cutter keeps the story above it.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Sequence

from manhwatok.adapters.lettering import rapid_ocr

MIN_SCORE = 0.6  # recognition confidence a line needs to count
EMPTY_PAGE = 0.7  # how much margin from which one scanlation line makes a stretch junk
TITLE_PAGE = 0.8  # how much margin from which the manhwa's name makes a title card
TITLE_LINES = 3  # lines a title may be set over (a logo is often read as broken words)
# A logo set letter by letter (vertically, in columns) reads as loose letters in no order: it is
# the title when nearly all the title's letters are there and little else is. Long names only.
LETTERS_FOUND = 0.9  # share of the title's letters read on the piece
LETTERS_EXTRA = 1.6  # how many letters the piece may hold, against the title's
LETTERS_MIN = 10  # letters a name needs for this to tell it apart
TITLE_MATCH = 0.8  # how close what is read has to be to one of the manhwa's names

WEBSITE = re.compile(
    r"https?://|www\.|[a-z0-9-]{2,}\s?\.\s?"
    r"(com|net|org|io|gg|me|to|xyz|site|online|co|cc|club|fun|lol|app|info|tv|live|ru)\b",
    re.IGNORECASE,
)
SCANLATION = re.compile(
    r"\b(translat\w*|editor|edited|proofread\w*|typeset\w*|cleaner|cleaning|redraw\w*|qc|"
    r"scans?|scanlat\w*|raws?|discord|patreon|ko-?fi|paypal|donat\w*|recruit\w*|credits|"
    r"read (it )?(at|on)|join (us|our)|(translated|brought to you|assistance|edited) by)\b|"
    r"\b(art|story|original|adapt\w*|illustrat\w*)\s*[:/]",
    re.IGNORECASE,
)

THE_END = re.compile(r"to be continued|continued in", re.IGNORECASE)  # the end card follows

# RapidOCR's call: (image path, use_cls=...) -> ([(box, text, score), ...] | None, elapsed)
Engine = Callable[..., tuple[Any, Any]]


def _plain(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum())


def _names_it(read: str, titles: Sequence[str]) -> bool:
    return len(read) >= 4 and any(
        name and SequenceMatcher(None, read, name).ratio() >= TITLE_MATCH
        for name in (_plain(title) for title in titles)
    )


def _spells_it(read: str, titles: Sequence[str]) -> bool:
    """Whether loose letters `read` are one of the titles' letters, in whatever order."""
    letters = Counter(read)
    for name in (_plain(title) for title in titles):
        if len(name) < LETTERS_MIN or len(read) > LETTERS_EXTRA * len(name):
            continue
        if sum((letters & Counter(name)).values()) >= LETTERS_FOUND * len(name):
            return True
    return False


def junk_from(
    found: list, titles: Sequence[str], margin: Sequence[float], ends: bool = True
) -> int | None:
    """The row junk starts at, given OCR results `found` on a piece and the share of each of its
    rows that is bare margin (0-1); None when it is all story. Only a piece at either `ends` of
    the chapter is judged on credits, websites and "To be continued"; one inside it (a title
    card after a cold open) only on the manhwa's name."""
    lines = sorted(
        (min(point[1] for point in box), text)
        for box, text, score in found
        if score >= MIN_SCORE and text.strip()
    )
    if not lines:
        return None
    starts = []
    hits = [top for top, text in lines if WEBSITE.search(text) or SCANLATION.search(text)]
    if ends and (len(hits) >= 2 or (hits and _empty(margin, min(hits)) >= EMPTY_PAGE)):
        starts.append(min(hits))
    named = [
        top
        for at, (top, text) in enumerate(lines)
        if (ends and THE_END.search(text))
        or any(
            _names_it(_plain("".join(text for _, text in lines[at:end])), titles)
            for end in range(at + 1, min(at + TITLE_LINES, len(lines)) + 1)
        )
    ]
    if not named and _spells_it(_plain("".join(text for _, text in lines)), titles):
        named = [top for top, _ in lines]
    if named and _empty(margin, min(named)) >= TITLE_PAGE:
        starts.append(min(named))
    return int(min(starts)) if starts else None


def _empty(margin: Sequence[float], top: float) -> float:
    """How much of the piece is bare margin from `top` down."""
    below = margin[max(0, int(top)) :]
    return sum(below) / len(below) if below else 1.0


class PanelJunk:
    """`check(piece, titles, margin, ends)` -> the row the piece stops being the story at, or None. The
    OCR model loads on first use."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    def __call__(
        self, path: Path, titles: Sequence[str], margin: Sequence[float], ends: bool = True
    ) -> int | None:
        engine = self._engine or rapid_ocr()
        found, _ = engine(str(path), use_cls=False)
        return junk_from(found or [], titles, margin, ends)
