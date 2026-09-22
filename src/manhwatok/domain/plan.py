"""An account's posting plan: the rotation of what its posts are about, taken in turn."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.theme import normalize_theme_name

CHAPTER = "chapter"  # the next part of a tracked title's chapters
THEME = "theme"  # a list post built from a saved theme


class RotationItem(BaseModel, frozen=True):
    """One step of a rotation. Written `chapter:<title>` (a title, or its AniList id, as
    `chapter build` takes it) or `theme:<name>` (a saved theme)."""

    kind: Literal["chapter", "theme"]
    value: str

    @classmethod
    def parse(cls, text: str) -> RotationItem:
        kind, colon, value = text.partition(":")
        kind, value = kind.strip().lower(), value.strip()
        if not colon or kind not in (CHAPTER, THEME):
            raise ManhwatokError(
                f"{text.strip()!r} is not a rotation item — write chapter:<title> or theme:<name>"
            )
        if not value:
            raise ManhwatokError(f"{text.strip()!r} names nothing — write {kind}:<something>")
        if kind == THEME:
            value = normalize_theme_name(value)
        return cls(kind=kind, value=value)

    def __str__(self) -> str:
        return f"{self.kind}:{self.value}"


def clean_rotation(items: list[str]) -> list[str]:
    """Each item checked and written the one way. Order and repeats are the plan's own: a
    rotation of chapter, theme, chapter posts that chapter twice as often."""
    return [str(RotationItem.parse(item)) for item in items]


def next_item(rotation: list[str], cursor: int) -> tuple[RotationItem, int]:
    """The item at `cursor` and where the cursor goes after it. Past the end it starts over,
    which also covers a cursor left beyond a rotation that has since been shortened."""
    if not rotation:
        raise ManhwatokError(
            "no rotation — set one with: manhwatok account set <handle> --rotation ..."
        )
    at = cursor % len(rotation)
    return RotationItem.parse(rotation[at]), (at + 1) % len(rotation)
