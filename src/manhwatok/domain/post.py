"""A recommendation-list post: ordered picks with hooks, plus the candidates it was built from."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, Field

from manhwatok.domain.models import Manhwa

DEFAULT_ACCENT = "#43c9e4"
DEFAULT_HASHTAGS = "#manhwa #manhwarecommendation #webtoon #manhwatiktok"
DEFAULT_CTA_TITLE = "Which one have you *read?*"
DEFAULT_CTA_FOLLOW = "Follow for part 2"
MAX_ITEMS = 33  # TikTok photo posts cap at 35 images: cover + items + end slide


class PostItem(BaseModel):
    manhwa: Manhwa
    hook: str = ""


class ListPost(BaseModel):
    id: str
    created_at: AwareDatetime
    title: str = ""
    items: list[PostItem] = Field(default_factory=list)
    candidates: list[Manhwa] = Field(default_factory=list)
    hashtags: str = DEFAULT_HASHTAGS
    accent: str = DEFAULT_ACCENT
    # Phase 3a fields; all defaulted so Phase 2 post.json files load unchanged.
    account: str | None = None  # handle without "@", or None for posts built without --account
    exported_at: AwareDatetime | None = None  # first export; its titles count as posted
    cta_title: str = DEFAULT_CTA_TITLE
    cta_follow: str = DEFAULT_CTA_FOLLOW

    @property
    def slide_count(self) -> int:
        return len(self.items) + 2

    @property
    def is_unfinished(self) -> bool:
        return not self.items
