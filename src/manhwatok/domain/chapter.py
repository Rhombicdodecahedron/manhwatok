"""A chapter post: one chapter of a manhwa, cut into slides and posted in parts.

A chapter is far longer than TikTok's 35 images, so it is split across several posts — part 1,
part 2 — and what was built and posted is tracked per title, so the next post continues where
the last one stopped. Nothing here does I/O: the records mirror what the store keeps, and the
rules over them (what order chapters come in, what to build next, how to split one) are pure.
"""

from __future__ import annotations

from typing import NamedTuple

from pydantic import AwareDatetime, BaseModel, Field

# TikTok photo posts cap at 35 images, and every post spends two of them on its cover and end
# slide. `post.MAX_ITEMS` is the same cap under the name the picks side uses.
SLIDES_PER_POST = 33


class ChapterPart(BaseModel):
    """The part of a chapter one post carries, and the panels it draws."""

    anilist_id: int
    manhwa_title: str  # drawn on the cover; post.title carries the *starred* styling
    number: str  # MangaDex's own chapter text: "12", "12.5", "" for a oneshot
    chapter_id: str  # the MangaDex chapter this came from
    language: str = "en"
    part: int = 1
    parts: int = 1
    panels: list[str] = Field(default_factory=list)  # files in the post folder, reading order
    pages: int = 0  # pages the whole chapter had, as the feed counted them
    from_panel: int = 0  # first panel of the whole chapter this post carries
    to_panel: int = 0  # one past the last, so "continue" is unambiguous


class ChapterRecord(BaseModel):
    """A chapter the source listed for a title."""

    anilist_id: int
    manhwa_title: str = ""
    number: str
    chapter_id: str
    language: str = "en"
    chapter_title: str = ""
    pages: int = 0
    downloaded_at: AwareDatetime | None = None


class PartRecord(BaseModel):
    """A part that was built into a post, and when that post went out."""

    anilist_id: int
    number: str
    language: str = "en"
    part: int
    parts: int
    post_id: str
    built_at: AwareDatetime
    published_at: AwareDatetime | None = None


class NextPart(NamedTuple):
    chapter: ChapterRecord
    part: int  # 1-based part to build next
    parts: int  # 0 when unknown: nothing of this chapter has been cut yet


def chapter_sort_key(number: str) -> tuple[int, float, str]:
    """Chapters by value, not by text: "2" before "12", "12.5" between "12" and "13". A chapter
    with no number (a oneshot) or a number that isn't one sorts after all of them."""
    try:
        return (0, float(number), "")
    except ValueError:
        return (1, 0.0, number)


def next_part(chapters: list[ChapterRecord], parts: list[PartRecord]) -> NextPart | None:
    """The part to build next: in chapter order, the first chapter nothing was built of, or the
    first with a part missing. None when every listed chapter is built.

    How many parts a chapter has is only known once it has been cut, and the parts already built
    record it — so a chapter no part exists for reports 0 and the caller cuts to find out."""
    built: dict[str, dict[int, PartRecord]] = {}
    for record in parts:
        built.setdefault(record.number, {})[record.part] = record
    for chapter in sorted(chapters, key=lambda c: chapter_sort_key(c.number)):
        done = built.get(chapter.number)
        if not done:
            return NextPart(chapter, 1, 0)
        total = max(record.parts for record in done.values())
        missing = [part for part in range(1, total + 1) if part not in done]
        if missing:
            return NextPart(chapter, missing[0], total)
    return None


def _whole(number: str) -> int | None:
    """A chapter number as a whole number, or None for "12.5", "extra" and the unnumbered."""
    try:
        value = float(number)
    except ValueError:
        return None
    return int(value) if value == int(value) else None


def starts_at(chapters: list[ChapterRecord]) -> str | None:
    """The first numbered chapter of the run, or None when none of them are numbered."""
    numbered = [c.number for c in chapters if _whole(c.number) is not None]
    return min(numbered, key=chapter_sort_key) if numbered else None


def missing_numbers(chapters: list[ChapterRecord]) -> list[str]:
    """Whole chapter numbers the source skipped inside the run it does have — a gap you would
    otherwise only notice after posting around it. Half-chapters and extras are not gaps."""
    whole = sorted({n for n in (_whole(c.number) for c in chapters) if n is not None})
    if len(whole) < 2:
        return []
    return [str(n) for n in range(whole[0], whole[-1]) if n not in set(whole)]


def part_slices(total: int, max_slides: int = SLIDES_PER_POST) -> list[tuple[int, int]]:
    """`total` panels split into as few posts as fit `max_slides` each, as evenly as the split
    allows: 34 panels are 17 and 17, not 33 and 1 — a one-slide part is not worth posting.
    Half-open (start, end) slices covering every panel once."""
    if total <= 0:
        return []
    posts = -(-total // max_slides)  # ceiling division
    size, extra = divmod(total, posts)
    slices = []
    start = 0
    for n in range(posts):
        end = start + size + (1 if n < extra else 0)
        slices.append((start, end))
        start = end
    return slices


def chapter_kicker(number: str, part: int, parts: int) -> str:
    """What the cover's pill says above the title."""
    if not number.strip():
        return "ONESHOT"
    chapter = f"CHAPTER {number}"
    return chapter if parts <= 1 else f"{chapter} · PART {part}/{parts}"
