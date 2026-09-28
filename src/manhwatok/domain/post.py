"""A recommendation-list post: ordered picks with hooks, plus the candidates it was built from."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from manhwatok.domain.chapter import SLIDES_PER_POST, ChapterPart
from manhwatok.domain.models import (
    ArtStyle,
    CharacterPick,
    ChapterCoverStyle,
    CoverStyle,
    Manhwa,
    PostKind,
    Visibility,
)

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
    # A characters post's pick: which of the title's characters this slide ranks.
    character: CharacterPick | None = None


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
    # The mark drawn at the foot of every slide; blank draws "@account" (nothing without one).
    byline: str = ""
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
    chapter_cover: ChapterCoverStyle = ChapterCoverStyle.FOCUS  # the same, for a chapter post
    # The theme it was built from, when it was: `upload` offers that theme's sounds first.
    theme: str | None = None
    # Who can see this post: None (the default, so older post.json files load) leaves it to
    # the account's own `visibility`. `upload --visibility` beats both, for that one upload.
    visibility: Visibility | None = None
    # A chapter post: its slides are this part of a chapter, drawn from `chapter.panels`
    # instead of from picks. None on every recommendation-list post.
    chapter: ChapterPart | None = None
    kind: PostKind = PostKind.LIST
    seed: Manhwa | None = None  # a similar post's "if you liked" title; never one of its items

    @model_validator(mode="after")
    def _chapter_kind(self) -> "ListPost":
        # Chapter posts saved before `kind` existed say so only by carrying a chapter.
        if self.chapter is not None and self.kind is not PostKind.CHAPTER:
            object.__setattr__(self, "kind", PostKind.CHAPTER)
        return self

    @property
    def slide_count(self) -> int:
        if self.chapter:
            return len(self.chapter.panels) + 2
        n = len(self.items)
        if self.kind is PostKind.VERSUS:
            return (n + 1) // 2 + 2
        if self.kind is PostKind.GUESS:
            return 2 * n + 2
        return n + 2

    @property
    def is_unfinished(self) -> bool:
        return not self.items and self.chapter is None

    @property
    def cover_styles(self) -> list[str]:
        """The cover versions a render draws for this kind of post."""
        return [s.value for s in (ChapterCoverStyle if self.chapter else CoverStyle)]

    @property
    def chosen_cover(self) -> str:
        """Which of `cover_styles` becomes 01.png."""
        return (self.chapter_cover if self.chapter else self.cover).value

    def with_cover(self, style: str) -> ListPost:
        """This post with `style` as its cover. Raises ValueError naming the styles this kind of
        post has when `style` isn't one of them."""
        if style not in self.cover_styles:
            kind = "a chapter post" if self.chapter else "a list post"
            raise ValueError(
                f"{style!r} is not a cover for {kind} — pick one of: {', '.join(self.cover_styles)}"
            )
        if self.chapter:
            return self.model_copy(update={"chapter_cover": ChapterCoverStyle(style)})
        return self.model_copy(update={"cover": CoverStyle(style)})


MAX_GUESS = (SLIDES_PER_POST - 1) // 2  # two slides a title, within a post's slides


def cover_kicker(post: ListPost) -> str:
    """The pill on a non-chapter cover: what the post holds."""
    n = len(post.items)
    if post.kind is PostKind.SIMILAR:
        return "IF YOU LIKED"
    if post.kind is PostKind.VERSUS:
        rounds = (n + 1) // 2
        return "1 ROUND" if rounds == 1 else f"{rounds} ROUNDS"
    if post.kind is PostKind.GUESS:
        return f"GUESS {n}"
    if post.kind is PostKind.CHARACTERS:
        return f"TOP {n}"
    return f"{n} PICK" if n == 1 else f"{n} PICKS"
