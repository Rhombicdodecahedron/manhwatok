"""A reusable theme: the AniList filters and title for one kind of post, shared by all accounts."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

from manhwatok.domain.errors import InvalidName, ManhwatokError
from manhwatok.domain.models import SearchQuery, Sort
from manhwatok.domain.text import clean_names, clean_sounds

_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def normalize_theme_name(raw: str) -> str:
    name = raw.strip().lower()
    if not _NAME.fullmatch(name):
        raise InvalidName(
            f"{raw!r} is not a theme name — use up to 40 lowercase letters, digits and '-', "
            "starting with a letter or digit"
        )
    return name


class Theme(BaseModel):
    # Validators raise ManhwatokError subclasses, which pydantic lets propagate unchanged.
    name: str
    tags: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    sort: Sort = Sort.SCORE
    min_tag_rank: int = 60
    title: str
    # TikTok sound searches that suit this kind of post (phonk for murim, soft pop for romance).
    # `upload` offers a post's theme sounds before its account's.
    sounds: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return normalize_theme_name(value)

    @field_validator("tags", "genres")
    @classmethod
    def _names(cls, value: list[str]) -> list[str]:
        return clean_names(value)

    @field_validator("sounds")
    @classmethod
    def _sounds(cls, value: list[str]) -> list[str]:
        return clean_sounds(value)

    @field_validator("min_tag_rank")
    @classmethod
    def _rank(cls, value: int) -> int:
        if not 0 <= value <= 100:
            raise ManhwatokError(f"min tag rank must be 0–100, got {value}")
        return value

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        if not value.strip():
            raise ManhwatokError("a theme needs a title")
        return value.strip()

    @model_validator(mode="after")
    def _has_filter(self) -> Theme:
        if not self.tags and not self.genres:
            raise ManhwatokError(f"theme {self.name}: give at least one tag or genre")
        return self

    def to_query(self, limit: int = 12) -> SearchQuery:
        return SearchQuery(
            tags=list(self.tags),
            genres=list(self.genres),
            sort=self.sort,
            limit=limit,
            min_tag_rank=self.min_tag_rank,
        )
