"""The Build forms' Chapter mode (TUI and web): what the form asks for, checked, and the two
things it does with it — say which part comes next (`chapter next`), or build it
(`chapter build`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from manhwatok.app.chapter_post import (
    ChapterTools,
    Chosen,
    build_chapter_post,
    chosen_part,
    next_to_build,
    pick_source,
    resolve_title,
    tracked_title,
)
from manhwatok.app.context import AppContext
from manhwatok.app.post_tools import PostTools, ProgressFn
from manhwatok.domain.account import Account
from manhwatok.domain.chapter import NextPart
from manhwatok.domain.color import check_accent
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import ChapterSourceName, Manhwa
from manhwatok.domain.post import ListPost

MAX_PARTS = 99  # parts of one chapter: far more than any chapter is cut into


@dataclass(frozen=True)
class ChapterRequest:
    """What the Chapter form asks for, read on the app thread for a worker to act on."""

    text: str  # a title typed in: a name or an AniList id; wins over `tracked`
    tracked: tuple[int, str] | None  # (AniList id, name) of the tracked title chosen
    source: ChapterSourceName | None  # None: the one it is tracked under, else the first with it
    language: str
    number: str | None  # a chapter asked for by name; None takes the next one in turn
    part: int | None  # which part of it; None takes the next unbuilt one
    account: Account | None
    title: str | None
    hashtags: str | None
    accent: str | None
    emojis: str | None

    @property
    def asked_for(self) -> bool:
        """Whether a chapter or part was named, rather than taken in turn."""
        return self.number is not None or self.part is not None


def chapter_request(
    text: str,
    tracked: tuple[int, str] | None,
    source: ChapterSourceName | None,
    language: str,
    number: str,
    part: str,
    account: Account | None,
    title: str,
    hashtags: str,
    accent: str,
    emojis: str,
) -> ChapterRequest:
    """The form's fields, checked. Raises ManhwatokError on what can be told without asking
    AniList or the source."""
    text = text.strip()
    if not text and tracked is None:
        raise ManhwatokError("name a title, or its AniList id")
    language = language.strip().lower()
    if not language:
        raise ManhwatokError("give a chapter language, e.g. en")
    accent = accent.strip()
    return ChapterRequest(
        text=text,
        tracked=tracked,
        source=source,
        language=language,
        number=number.strip() or None,
        part=_part(part),
        account=account,
        title=title.strip() or None,
        hashtags=hashtags.strip() or None,
        accent=check_accent(accent) if accent else None,
        emojis=emojis.strip() or None,
    )


def _part(raw: str) -> int | None:
    if not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if not 1 <= value <= MAX_PARTS:
        raise ManhwatokError(f"part must be a whole number from 1 to {MAX_PARTS}")
    return value


def next_line(manhwa: Manhwa, source: ChapterSourceName, found: NextPart | None) -> str:
    """What `chapter next` says, in one line."""
    where = f"{manhwa.title} · {source.value}"
    if found is None:
        return f"{where} — every listed chapter is built"
    parts = f" of {found.parts}" if found.parts else ""
    return f"{where} — next: chapter {found.chapter.number}, part {found.part}{parts}"


def chosen_line(manhwa: Manhwa, source: ChapterSourceName, chosen: Chosen) -> str:
    """What Check says about a chapter and part asked for by name."""
    found = chosen.part
    parts = f" of {found.parts}" if found.parts else ""
    built = " — built already" if chosen.built else ""
    return (
        f"{manhwa.title} · {source.value} — asked for: chapter {found.chapter.number}, "
        f"part {found.part}{parts}{built}"
    )


def title_tools(
    ctx: AppContext, req: ChapterRequest, progress: ProgressFn
) -> tuple[Manhwa, ChapterTools]:
    """The title asked for and the chapter tools of its source."""
    if req.text or req.tracked is None:
        manhwa = resolve_title(req.text, ctx.metadata, ctx.store.cache)
    else:
        manhwa = tracked_title(*req.tracked, ctx.metadata, ctx.store.cache)
    ct = pick_source(manhwa, ctx.chapter_tools, req.language, req.source, progress)
    return manhwa, ct


def check_chapter(
    ctx: AppContext, req: ChapterRequest, now: datetime, progress: ProgressFn
) -> str:
    """What would be built, in one line — listing the title from its source when nothing (or
    nothing unbuilt) is on record, which starts tracking it."""
    manhwa, ct = title_tools(ctx, req, progress)
    if req.asked_for:
        chosen = chosen_part(manhwa, ct, now, req.number, req.part, req.language, progress)
        return chosen_line(manhwa, ct.source, chosen)
    return next_line(manhwa, ct.source, next_to_build(manhwa, ct, now, req.language, progress))


def build_requested(
    ctx: AppContext, req: ChapterRequest, tools: PostTools, now: datetime
) -> tuple[ListPost, list[Path]]:
    """Build and render the part asked for, or the next one; progress goes to `tools`."""
    progress = tools.progress
    manhwa, ct = title_tools(ctx, req, progress)
    if not req.asked_for and next_to_build(manhwa, ct, now, req.language, progress) is None:
        raise ManhwatokError(
            f"every listed chapter of {manhwa.title} is already built — "
            f"{ct.source.value} has nothing new"
        )
    return build_chapter_post(
        manhwa,
        tools,
        ct,
        req.account,
        now,
        number=req.number,
        part=req.part,
        language=req.language,
        title=req.title,
        hashtags=req.hashtags,
        accent=req.accent,
        emojis=req.emojis,
    )


def built_line(post: ListPost, slides: list[Path]) -> str:
    """What a finished build says."""
    where = post.chapter
    return (
        f"post {post.id} · chapter {where.number} part {where.part}/{where.parts} · "
        f"{len(slides)} slides"
    )
