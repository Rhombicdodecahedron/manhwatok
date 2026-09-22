from pathlib import Path
from typing import Callable, NamedTuple, Protocol

from manhwatok.domain.models import Manhwa


class ChapterInfo(NamedTuple):
    """One chapter a source has, before anything is downloaded."""

    chapter_id: str
    number: str  # the source's own text: "12", "12.5"; "" for an unnumbered oneshot
    title: str
    language: str
    pages: int


class PageCount(str):
    """A progress message that is also a count — "chapter 13: page 12 of 37" — so a terminal
    can draw it as a bar, while anything that only wants text reads it as the message."""

    label: str
    done: int
    total: int

    def __new__(cls, label: str, unit: str, done: int, total: int) -> "PageCount":
        count = super().__new__(cls, f"{label}: {unit} {done} of {total}")
        count.label, count.done, count.total = label, done, total
        return count


class ChapterPagesSource(Protocol):
    def chapters(self, manhwa: Manhwa, language: str = "en") -> list[ChapterInfo]:
        """Every chapter this source has in `language`, in chapter-number order. Empty when it
        has no such title, or has it with no chapter in that language."""
        ...

    def other_languages(self, manhwa: Manhwa, before: str, language: str = "en") -> dict[str, int]:
        """How many chapters numbered below `before` each other language has — what you are
        missing, and where it could be read from instead. Empty when nothing is missing."""
        ...

    def pages(
        self, chapter: ChapterInfo, progress: Callable[[str], None] | None = None
    ) -> list[Path]:
        """The chapter's pages on disk in reading order, downloading whatever is missing."""
        ...

    def cached_pages(self, chapter: ChapterInfo) -> list[Path]:
        """Pages already downloaded, in order; empty unless the whole chapter is there. Never
        downloads."""
        ...


class PanelCutter(Protocol):
    def cut(self, pages: list[Path], out_dir: Path, prefix: str = "panel") -> list[Path]:
        """The pages joined in reading order and cut into slide-sized panels, written into
        `out_dir` and returned in order. A folder already cut is reused, not cut again."""
        ...
