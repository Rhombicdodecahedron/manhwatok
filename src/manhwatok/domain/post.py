"""A recommendation-list post: ordered picks with hooks, plus the candidates it was built from."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from manhwatok.domain.models import Manhwa

DEFAULT_ACCENT = "#43c9e4"
DEFAULT_HASHTAGS = "#manhwa #manhwarecommendation #webtoon #manhwatiktok"
MAX_ITEMS = 33  # TikTok photo posts cap at 35 images: cover + items + end slide


class PostItem(BaseModel):
    manhwa: Manhwa
    hook: str = ""


class ListPost(BaseModel):
    id: str
    created_at: datetime
    title: str = ""
    items: list[PostItem] = Field(default_factory=list)
    candidates: list[Manhwa] = Field(default_factory=list)
    hashtags: str = DEFAULT_HASHTAGS
    accent: str = DEFAULT_ACCENT

    @property
    def slide_count(self) -> int:
        return len(self.items) + 2

    @property
    def is_unfinished(self) -> bool:
        return not self.items
