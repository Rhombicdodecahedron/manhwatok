"""A recommendation-list post: ordered picks with hooks, plus the candidates it was built from."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, Field

from manhwatok.domain.chapter import SLIDES_PER_POST, ChapterPart
from manhwatok.domain.models import ArtStyle, CoverStyle, Manhwa, Visibility

DEFAULT_ACCENT = "#43c9e4"
DEFAULT_HASHTAGS = "#manhwa #manhwarecommendation #webtoon #manhwatiktok"
DEFAULT_CTA_TITLE = "Which one have you *read?*"
DEFAULT_CTA_FOLLOW = "Follow for part 2"
MAX_ITEMS = SLIDES_PER_POST  # picks per post: the same cap the panels of a chapter post get


class PostItem(BaseModel):
    manhwa: Manhwa
    hook: str = ""
    # A file the user picked by hand, kept in the post's own folder and named relative to it.
    # It beats whatever the post's art style would have fetched.
    custom_art: str = ""
    # Extra pictures for the quad style, where the title's characters leave gaps: files in the
    # post's folder, in the order they fill the grid.
    scenes: list[str] = Field(default_factory=list)


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
    # When it's planned to go out: one of its account's slots (`plan fill`) or a time set with
    # `schedule`. It keeps its slot once sent, so the slot isn't filled again.
    scheduled_at: AwareDatetime | None = None
    # Phase D: the time TikTok's own schedule was filled in with, once the user confirmed they
    # clicked Schedule. TikTok posts it then, without manhwatok.
    tiktok_scheduled_at: AwareDatetime | None = None
    # Phase 5: a post keeps the art style it was built with, as it keeps its CTA texts.
    art: ArtStyle = ArtStyle.NONE
    cover: CoverStyle = CoverStyle.FAN  # which cover version render makes 01.png
    # The theme it was built from, when it was: `upload` offers that theme's sounds first.
    theme: str | None = None
    # Who can see this post: None (the default, so older post.json files load) leaves it to
    # the account's own `visibility`. `upload --visibility` beats both, for that one upload.
    visibility: Visibility | None = None
    # A chapter post: its slides are this part of a chapter, drawn from `chapter.panels`
    # instead of from picks. None on every recommendation-list post.
    chapter: ChapterPart | None = None

    @property
    def slide_count(self) -> int:
        drawn = len(self.chapter.panels) if self.chapter else len(self.items)
        return drawn + 2

    @property
    def is_unfinished(self) -> bool:
        return not self.items and self.chapter is None
