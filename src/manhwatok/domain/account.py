"""A TikTok account the tool posts for: its genre filters, hashtags, accent and end-slide texts."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from manhwatok.domain.color import check_accent
from manhwatok.domain.errors import InvalidName, ManhwatokError
from manhwatok.domain.models import ArtStyle
from manhwatok.domain.post import (
    DEFAULT_ACCENT,
    DEFAULT_CTA_FOLLOW,
    DEFAULT_CTA_TITLE,
    DEFAULT_HASHTAGS,
)
from manhwatok.domain.text import clean_names

DEFAULT_REPEAT_DAYS = 30
MAX_REPEAT_DAYS = 3650
_HANDLE = re.compile(r"[a-z0-9._]{2,24}")


def normalize_handle(raw: str) -> str:
    """'@Manhwa.Daily' -> 'manhwa.daily'. Raises InvalidName unless 2–24 of a-z 0-9 . _, with at least one letter or digit"""
    handle = raw.strip().lower().removeprefix("@")
    if not _HANDLE.fullmatch(handle):
        raise InvalidName(f"{raw!r} is not a TikTok handle — use 2–24 letters, digits, '.' or '_'")
    if not any(c in handle for c in "abcdefghijklmnopqrstuvwxyz0123456789"):
        raise InvalidName(f"{raw!r} is not a TikTok handle — use 2–24 letters, digits, '.' or '_', and at least one letter or digit")
    return handle


class Account(BaseModel):
    # Validators raise ManhwatokError subclasses, which pydantic lets propagate unchanged.
    handle: str  # stored lowercase without "@"
    genres: list[str] = Field(default_factory=list)  # allow-list: a title needs at least one
    block_genres: list[str] = Field(default_factory=list)
    block_tags: list[str] = Field(default_factory=list)
    hashtags: str = DEFAULT_HASHTAGS
    emojis: str = ""  # after the title in TikTok's title field; never drawn on a slide
    # TikTok sound searches (e.g. "SOLO LEVELING RaijinLofi"); `upload` asks which one to use.
    sounds: list[str] = Field(default_factory=list)
    accent: str = DEFAULT_ACCENT
    cta_title: str = DEFAULT_CTA_TITLE
    cta_follow: str = DEFAULT_CTA_FOLLOW
    repeat_days: int = DEFAULT_REPEAT_DAYS
    art: ArtStyle = ArtStyle.NONE  # default for this account's new posts

    @field_validator("handle")
    @classmethod
    def _handle(cls, value: str) -> str:
        return normalize_handle(value)

    @field_validator("genres", "block_genres", "block_tags")
    @classmethod
    def _names(cls, value: list[str]) -> list[str]:
        return clean_names(value)

    @field_validator("emojis")
    @classmethod
    def _emojis(cls, value: str) -> str:
        return value.strip()

    @field_validator("sounds")
    @classmethod
    def _sounds(cls, value: list[str]) -> list[str]:
        sounds: list[str] = []
        for sound in (" ".join(s.split()) for s in value):
            if sound and sound not in sounds:
                sounds.append(sound)
        return sounds

    @field_validator("accent")
    @classmethod
    def _accent(cls, value: str) -> str:
        return check_accent(value)

    @field_validator("cta_title", "cta_follow")
    @classmethod
    def _cta(cls, value: str) -> str:
        if not value.strip():
            raise ManhwatokError("end-slide texts can't be empty")
        return value.strip()

    @field_validator("repeat_days")
    @classmethod
    def _repeat_days(cls, value: int) -> int:
        if not 1 <= value <= MAX_REPEAT_DAYS:
            raise ManhwatokError(f"repeat days must be 1–{MAX_REPEAT_DAYS}, got {value}")
        return value

    @property
    def display(self) -> str:
        return f"@{self.handle}"
