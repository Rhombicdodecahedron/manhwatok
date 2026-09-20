"""Building a chapter post: fetch a chapter, cut it into slides, post it a part at a time.

What exists is the source's to say, what is on this disk and what has been posted is the
store's, and which part comes next is the domain's (`chapter.next_part`). This module is the
sequence that joins them: list, download, cut, take this part's share, render, record.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from manhwatok.app.build_post import _save_new
from manhwatok.app.post_tools import PostTools, ProgressFn
from manhwatok.app.render_post import render_post
from manhwatok.domain.account import Account
from manhwatok.domain.chapter import (
    ChapterPart,
    ChapterRecord,
    PartRecord,
    missing_numbers,
    next_part,
    part_slices,
    starts_at,
)
from manhwatok.domain.errors import ManhwatokError, MetadataError
from manhwatok.domain.models import ChapterSourceName, Manhwa
from manhwatok.domain.post import (
    DEFAULT_ACCENT,
    DEFAULT_CTA_TITLE,
    DEFAULT_HASHTAGS,
    ListPost,
)
from manhwatok.ports.cache import Cache
from manhwatok.ports.chapters import ChapterInfo, ChapterPagesSource, PanelCutter
from manhwatok.ports.metadata import MetadataSource
from manhwatok.ports.store import ChapterRepository

LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "es-la": "Latin American Spanish",
    "pt-br": "Portuguese",
    "fr": "French",
    "it": "Italian",
    "pl": "Polish",
    "de": "German",
    "id": "Indonesian",
    "ru": "Russian",
    "tr": "Turkish",
    "vi": "Vietnamese",
}
PANEL_PREFIX = "panel-"
PANELS_DIR = "panels"  # where a chapter's cut panels live, beside its pages


def _noop(_: str) -> None:
    pass


@dataclass
class ChapterTools:
    """What a chapter post needs beyond the usual PostTools. `sources` holds every place
    chapters can come from; `pages` is the one a command settled on."""

    pages: ChapterPagesSource
    cutter: PanelCutter
    chapters: ChapterRepository
    pages_dir: Path
    source: ChapterSourceName = ChapterSourceName.MANGADEX
    sources: dict[ChapterSourceName, ChapterPagesSource] = field(default_factory=dict)

    def using(self, source: ChapterSourceName) -> "ChapterTools":
        """The same tools, reading from `source`."""
        return ChapterTools(
            pages=self.sources.get(source, self.pages),
            cutter=self.cutter,
            chapters=self.chapters,
            pages_dir=self.pages_dir,
            source=source,
            sources=self.sources,
        )


class ChapterStatus(NamedTuple):
    chapter: ChapterRecord
    parts: list[PartRecord]

    @property
    def built(self) -> int:
        return len(self.parts)

    @property
    def published(self) -> int:
        return len([p for p in self.parts if p.published_at])


def pick_source(
    manhwa: Manhwa,
    ct: ChapterTools,
    language: str = "en",
    wanted: ChapterSourceName | None = None,
    progress: ProgressFn = _noop,
) -> ChapterTools:
    """The tools to use for this title: the source asked for, else the one it is already
    tracked under, else the first that has it. A title keeps its source — chapter 12 does not
    mean the same thing in two catalogues, and what was posted is counted by number."""
    if wanted is not None:
        return ct.using(wanted)
    known = ct.chapters.sources_of(manhwa.anilist_id, language)
    if known:
        return ct.using(known[0])
    order = [ct.source, *(s for s in ct.sources if s != ct.source)]
    for name in order:
        trying = ct.using(name)
        try:
            if trying.pages.chapters(manhwa, language):
                if name != order[0]:
                    progress(f"{manhwa.title}: {order[0].value} has nothing, using {name.value}")
                return trying
        except MetadataError as e:
            progress(f"{name.value}: {e}")
    return ct.using(order[0])


def resolve_title(text: str, metadata: MetadataSource, cache: Cache | None = None) -> Manhwa:
    """The title the user named: an AniList id, or a search. Remembered by id, so naming it
    once is enough and later commands cost nothing."""
    wanted = text.strip()
    if not wanted:
        raise ManhwatokError("name a title, or its AniList id")
    if wanted.isdigit() and cache is not None:
        hit = cache.get(f"manhwa:{wanted}", float("inf"))
        if hit:
            return Manhwa.model_validate_json(hit)
    found = metadata.find(wanted)
    if not found:
        raise ManhwatokError(f"AniList has nothing called {wanted!r}")
    exact = [m for m in found if m.title.lower() == wanted.lower() or str(m.anilist_id) == wanted]
    if len(found) > 1 and not exact:
        names = ", ".join(f"{m.title} ({m.anilist_id})" for m in found[:5])
        raise ManhwatokError(f"which one? {names} — name it exactly, or give its AniList id")
    manhwa = exact[0] if exact else found[0]
    if cache is not None:
        cache.put(f"manhwa:{manhwa.anilist_id}", manhwa.model_dump_json())
    return manhwa


def refresh_chapters(
    manhwa: Manhwa,
    ct: ChapterTools,
    now: datetime,
    language: str = "en",
    progress: ProgressFn = _noop,
) -> list[ChapterRecord]:
    """Read the source's chapter list and record it. What is already known about a chapter on
    this disk — that its pages were downloaded — survives."""
    found = ct.pages.chapters(manhwa, language)
    if not found:
        named = LANGUAGES.get(language, language)
        where = "MangaDex" if ct.source is ChapterSourceName.MANGADEX else "WEBTOON"
        raise ManhwatokError(
            f"{manhwa.title}: no {named} chapters to publish — {where} either has no entry for "
            f"it, or has it with nothing in {named}"
        )
    progress(f"{manhwa.title}: {len(found)} chapters listed")
    ct.chapters.record_chapters(
        [
            ChapterRecord(
                source=ct.source,
                anilist_id=manhwa.anilist_id,
                manhwa_title=manhwa.title,
                number=info.number,
                chapter_id=info.chapter_id,
                language=info.language,
                chapter_title=info.title,
                pages=info.pages,
            )
            for info in found
        ]
    )
    return ct.chapters.chapters(manhwa.anilist_id, language, ct.source)


def chapter_status(
    anilist_id: int, ct: ChapterTools, language: str = "en"
) -> list[ChapterStatus]:
    """Every chapter known for the title, with the parts built of it."""
    parts = ct.chapters.parts(anilist_id, language, ct.source)
    return [
        ChapterStatus(chapter, [p for p in parts if p.number == chapter.number])
        for chapter in ct.chapters.chapters(anilist_id, language, ct.source)
    ]


def missing_report(
    manhwa: Manhwa,
    ct: ChapterTools,
    known: list[ChapterRecord],
    language: str = "en",
) -> list[str]:
    """What the source hasn't got: where the run starts, the holes inside it, and which other
    languages have the chapters before it. Said plainly, because a run that starts at chapter
    12 is something to know before building a post, not after."""
    named = LANGUAGES.get(language, language)
    lines = []
    first = starts_at(known)
    if first and first not in ("0", "1"):
        lines.append(f"{named} starts at chapter {first} — MangaDex has nothing before it")
        counts = ct.pages.other_languages(manhwa, first, language)
        if counts:
            where = ", ".join(
                f"{LANGUAGES.get(code, code)} ({count})"
                for code, count in sorted(counts.items(), key=lambda pair: -pair[1])
            )
            lines.append(f"  chapters 1–{int(float(first)) - 1} are there in: {where}")
    holes = missing_numbers(known)
    if holes:
        shown = ", ".join(holes[:8]) + (" …" if len(holes) > 8 else "")
        lines.append(f"missing from the {named} run: {shown}")
    return lines


def build_chapter_post(
    manhwa: Manhwa,
    tools: PostTools,
    ct: ChapterTools,
    account: Account | None,
    now: datetime,
    number: str | None = None,
    part: int | None = None,
    language: str = "en",
    title: str | None = None,
    hashtags: str | None = None,
    accent: str | None = None,
    emojis: str | None = None,
    theme: str | None = None,
) -> tuple[ListPost, list[Path]]:
    """One post: the chapter's pages downloaded, cut into panels, this part's share copied into
    the post's own folder and rendered. `number` and `part` default to continuing where the
    last post of this title stopped."""
    known = ct.chapters.chapters(manhwa.anilist_id, language, ct.source)
    if not known:
        known = refresh_chapters(manhwa, ct, now, language, tools.progress)
    chapter, part = _which(known, ct, manhwa, language, number, part)
    info = ChapterInfo(
        chapter_id=chapter.chapter_id,
        number=chapter.number,
        title=chapter.chapter_title,
        language=chapter.language,
        pages=chapter.pages,
    )
    pages = ct.pages.pages(info, tools.progress)
    ct.chapters.mark_downloaded(manhwa.anilist_id, chapter.number, language, now, ct.source)
    panels = ct.cutter.cut(pages, ct.pages_dir / chapter.chapter_id / PANELS_DIR)
    if not panels:
        raise ManhwatokError(f"{manhwa.title} chapter {chapter.number}: nothing to cut into slides")
    slices = part_slices(len(panels))
    if part > len(slices):
        raise ManhwatokError(
            f"{manhwa.title} chapter {chapter.number} is {len(slices)} part"
            f"{'s' if len(slices) != 1 else ''} — there is no part {part}"
        )
    start, end = slices[part - 1]
    post_id = tools.posts.new_id(now.astimezone().date())
    names = _copy_panels(panels[start:end], tools.posts.folder(post_id))
    chapter_part = ChapterPart(
        source=ct.source,
        anilist_id=manhwa.anilist_id,
        manhwa_title=manhwa.title,
        number=chapter.number,
        chapter_id=chapter.chapter_id,
        language=language,
        part=part,
        parts=len(slices),
        panels=names,
        pages=chapter.pages,
        from_panel=start,
        to_panel=end,
    )
    post = create_chapter_post(
        post_id, now, manhwa, chapter_part, title, account, hashtags, accent, emojis, theme
    )
    _save_new(post, tools.posts)
    slides = render_post(post.id, tools)
    ct.chapters.record_part(
        PartRecord(
            source=ct.source,
            anilist_id=manhwa.anilist_id,
            number=chapter.number,
            language=language,
            part=part,
            parts=len(slices),
            post_id=post.id,
            built_at=now,
        )
    )
    return post, slides


def create_chapter_post(
    post_id: str,
    now: datetime,
    manhwa: Manhwa,
    chapter: ChapterPart,
    title: str | None,
    account: Account | None,
    hashtags: str | None,
    accent: str | None,
    emojis: str | None = None,
    theme: str | None = None,
) -> ListPost:
    """A new chapter post (pure). Style comes from the override, else the account, else the
    defaults — as a list post's does."""
    named = title or f"{manhwa.title} *Chapter {chapter.number}*".replace(" *Chapter *", "")
    cta_title = account.cta_title if account else DEFAULT_CTA_TITLE
    if cta_title == DEFAULT_CTA_TITLE:
        # "Which one have you read?" is a list post's question; a chapter post says what comes
        # next instead. An account that wrote its own end-slide title keeps it.
        cta_title = end_title(chapter)
    return ListPost(
        id=post_id,
        created_at=now,
        title=named,
        items=[],
        candidates=[],
        chapter=chapter,
        hashtags=hashtags if hashtags is not None else (account.hashtags if account else DEFAULT_HASHTAGS),
        emojis=emojis if emojis is not None else (account.emojis if account else ""),
        accent=accent if accent is not None else (account.accent if account else DEFAULT_ACCENT),
        account=account.handle if account else None,
        cta_title=cta_title,
        cta_follow=account.cta_follow if account else ListPost.model_fields["cta_follow"].default,
        theme=theme,
    )


def end_title(chapter: ChapterPart) -> str:
    """What the end slide says above the follow line."""
    if chapter.part < chapter.parts:
        return f"Part *{chapter.part + 1}* next"
    if chapter.number:
        return f"Chapter *{chapter.number}* done"
    return "*The end*"


def _which(
    known: list[ChapterRecord],
    ct: ChapterTools,
    manhwa: Manhwa,
    language: str,
    number: str | None,
    part: int | None,
) -> tuple[ChapterRecord, int]:
    """The chapter and part to build: what was asked for, else what comes next."""
    if number is not None:
        wanted = [c for c in known if c.number == number]
        if not wanted:
            listed = ", ".join(c.number for c in known) or "nothing"
            raise ManhwatokError(
                f"{manhwa.title} has no chapter {number} in {language} — listed: {listed}"
            )
        return wanted[0], part or _next_of(ct, manhwa, language, number)
    found = next_part(known, ct.chapters.parts(manhwa.anilist_id, language, ct.source))
    if found is None:
        raise ManhwatokError(
            f"every listed chapter of {manhwa.title} is already built — "
            f"run `manhwatok chapter list {manhwa.anilist_id} --refresh` for new ones"
        )
    return found.chapter, part or found.part


def _next_of(ct: ChapterTools, manhwa: Manhwa, language: str, number: str) -> int:
    """The first part of this chapter not built yet (1 when none are)."""
    parts = ct.chapters.parts(manhwa.anilist_id, language, ct.source)
    built = {p.part for p in parts if p.number == number}
    part = 1
    while part in built:
        part += 1
    return part


def _copy_panels(panels: list[Path], folder: Path) -> list[str]:
    """This part's panels, copied into the post's folder so it stays self-contained."""
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob(f"{PANEL_PREFIX}*"):
        old.unlink()
    names = []
    for n, panel in enumerate(panels, 1):
        name = f"{PANEL_PREFIX}{n:03d}{panel.suffix.lower() or '.png'}"
        shutil.copyfile(panel, folder / name)
        names.append(name)
    return names
