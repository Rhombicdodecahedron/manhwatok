"""A recommendation-list post: ordered picks with hooks, plus the candidates it was built from."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, Field

from manhwatok.domain.models import ArtStyle, Manhwa

DEFAULT_ACCENT = "#43c9e4"
DEFAULT_HASHTAGS = "#manhwa #manhwarecommendation #webtoon #manhwatiktok"
DEFAULT_CTA_TITLE = "Which one have you *read?*"
DEFAULT_CTA_FOLLOW = "Follow for part 2"
MAX_ITEMS = 33  # TikTok photo posts cap at 35 images: cover + items + end slide


class PostItem(BaseModel):
    manhwa: Manhwa
    hook: str = ""
    # A file the user picked by hand, kept in the post's own folder and named relative to it.
    # It beats whatever the post's art style would have fetched.
    custom_art: str = ""


class ListPost(BaseModel):
    id: str
    created_at: AwareDatetime
    title: str = ""
    items: list[PostItem] = Field(default_factory=list)
    candidates: list[Manhwa] = Field(default_factory=list)
    hashtags: str = DEFAULT_HASHTAGS
    emojis: str = ""  # after the title in TikTok's title field; never drawn on a slide
    accent: str = DEFAULT_ACCENT
    # Phase 3a fields; all defaulted so Phase 2 post.json files load unchanged.
    account: str | None = None  # handle without "@", or None for posts built without --account
    exported_at: AwareDatetime | None = None  # first export; its titles count as posted
    cta_title: str = DEFAULT_CTA_TITLE
    cta_follow: str = DEFAULT_CTA_FOLLOW
    sent_at: AwareDatetime | None = None  # Phase 4: when the user confirmed it was posted
    # Phase 5: a post keeps the art style it was built with, as it keeps its CTA texts.
    art: ArtStyle = ArtStyle.NONE

    @property
    def slide_count(self) -> int:
        return len(self.items) + 2

    @property
    def is_unfinished(self) -> bool:
        return not self.items
