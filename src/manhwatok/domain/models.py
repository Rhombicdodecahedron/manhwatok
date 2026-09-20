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


QUAD_PICTURES = 4  # pictures on a quad slide or cover


class ArtStyle(StrEnum):
    """What art a manhwa slide is built around."""

    NONE = "none"  # the cover, blurred, behind its own card — the original look
    BACKGROUND = "background"  # AniList's banner behind the cover card, cover blur as fallback
    PANEL = "panel"  # a wide crop of the banner (or the cover) in place of the card
    CHARACTER = "character"  # the title's main character in place of the cover
    SCENE = "scene"  # one picture filling the whole slide, text over it
    QUAD = "quad"  # four of the title's own pictures, 2×2 over the whole slide, text over them


class CoverStyle(StrEnum):
    """What the cover slide is built around. Every render draws all of them; the post's choice
    becomes 01.png and the rest wait beside it as cover-<style>.png."""

    FAN = "fan"  # the first three covers fanned out — the original look
    QUAD = "quad"  # four characters, one per quadrant of the slide
    HERO = "hero"  # the first pick's art filling the whole slide


class ArtSourceName(StrEnum):
    """Where a title's alternative art is looked for."""

    COVERS = "covers"  # MangaDex volume covers: publisher art, paired on the AniList id
    FANART = "fanart"  # Danbooru, best-scored and safe-rated only: art by individual artists
    PINS = "pins"  # a Pinterest search: most pictures, no artist recorded for any of them
    REDDIT = "reddit"  # image posts naming the title, most-upvoted first


class ChapterSourceName(StrEnum):
    """Where a chapter's pages come from. A title sticks to one: chapter numbers do not mean
    the same thing in two catalogues, so mixing them would mix up what was already posted."""

    MANGADEX = "mangadex"  # fan translations, wide catalogue, often missing the early run
    WEBTOONS = "webtoons"  # the publisher's own English, from episode 1, free episodes only


class ArtOrder(StrEnum):
    """How a list of art options is arranged before you pick from it."""

    RELEVANCE = "relevance"  # the source's own order: Pinterest's ranking, a booru's score
    SIZE = "size"  # biggest picture first
    PORTRAIT = "portrait"  # closest to a slide's 9:16 first
    POPULAR = "popular"  # most liked first, where the source counts likes (Pinterest)


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
    banner_url: str = ""  # AniList bannerImage; about half of manhwa have none
    character_url: str = ""  # the title's most-favourited character, when AniList has a picture
    # Up to QUAD_PICTURES pictured characters, most favourited first (character_url is the
    # first). Empty on titles saved before it existed: `characters` falls back then.
    character_urls: list[str] = Field(default_factory=list)
    # AniList's other names for the title ("Murim Login" for Log-in Murim), which fan art is
    # often filed under. None on titles saved before it existed: not looked up yet.
    synonyms: list[str] | None = None
    description: str = ""
    site_url: str = ""

    @property
    def characters(self) -> list[str]:
        """Pictured characters' image URLs, most favourited first."""
        if self.character_urls:
            return list(self.character_urls)
        return [self.character_url] if self.character_url else []

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
