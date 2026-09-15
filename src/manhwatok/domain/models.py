"""Core domain models. No I/O."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Status(StrEnum):
    FINISHED = "FINISHED"
    RELEASING = "RELEASING"
    NOT_YET_RELEASED = "NOT_YET_RELEASED"
    CANCELLED = "CANCELLED"
    HIATUS = "HIATUS"
    UNKNOWN = "UNKNOWN"


class Manhwa(BaseModel):
    anilist_id: int
    title: str
    romaji: str
    status: Status
    chapters: int | None = None
    latest_chapter: int | None = None
    start_year: int | None = None
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    score: int | None = None
    popularity: int = 0
    cover_url: str = ""
    cover_color: str | None = None
    description: str = ""
    site_url: str = ""

    @property
    def chapter_count(self) -> int | None:
        return self.chapters if self.chapters is not None else self.latest_chapter


class Sort(StrEnum):
    SCORE = "score"
    POPULARITY = "popularity"
    TRENDING = "trending"


class SearchQuery(BaseModel):
    tags: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    sort: Sort = Sort.SCORE
    limit: int = Field(default=12, ge=1, le=50)
    min_tag_rank: int = Field(default=60, ge=0, le=100)
    exclude_genres: list[str] = Field(default_factory=list)  # AniList genre_not_in
    exclude_tags: list[str] = Field(default_factory=list)  # AniList tag_not_in


class TagInfo(BaseModel):
    name: str
    category: str
    description: str = ""
