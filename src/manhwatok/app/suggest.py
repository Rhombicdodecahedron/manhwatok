"""Suggest manhwa for a theme: AniList search (narrowed by an account's filters and repeat
history), then fill in missing chapter counts."""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import zip_longest
from typing import Callable

from manhwatok.domain.account import Account
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Manhwa, SearchQuery, Sort
from manhwatok.domain.text import clean_names
from manhwatok.ports.metadata import ChapterSource, MetadataSource
from manhwatok.ports.store import HistoryRepository

MAX_FETCH = 50  # AniList's perPage limit


def _noop(_: str) -> None:
    pass


def suggest_titles(
    query: SearchQuery,
    metadata: MetadataSource,
    chapters: ChapterSource | None = None,
    progress: Callable[[str], None] = _noop,
) -> list[Manhwa]:
    return _fill_chapters(metadata.search(query), chapters, progress)


def suggest_for_account(
    query: SearchQuery,
    account: Account | None,
    metadata: MetadataSource,
    chapters: ChapterSource | None,
    history: HistoryRepository,
    now: datetime,
    allow_repeats: bool = False,
    progress: Callable[[str], None] = _noop,
) -> list[Manhwa]:
    """`suggest_titles` when there is no account. Otherwise: exclude the account's blocked
    genres/tags (in the search and again locally), search once per allowed genre (AniList's
    genre_in is AND, an allow-list is OR), and drop titles the account exported within its
    repeat window (fetching extra to make up)."""
    if account is None:
        return suggest_titles(query, metadata, chapters, progress)
    query = query.model_copy(
        update={
            "exclude_genres": clean_names(query.exclude_genres + account.block_genres),
            "exclude_tags": clean_names(query.exclude_tags + account.block_tags),
        }
    )
    recent: set[int] = set()
    if not allow_repeats:
        recent = history.recent(account.handle, now - timedelta(days=account.repeat_days))
    fetch = query.model_copy(update={"limit": min(MAX_FETCH, query.limit + len(recent))})
    if account.genres:
        lists = [
            metadata.search(fetch.model_copy(update={"genres": clean_names(query.genres + [g])}))
            for g in account.genres
        ]
        results = merge_results(lists, query.sort)
    else:
        results = metadata.search(fetch)
    results = _drop_blocked(results, query)
    skipped = sum(1 for m in results if m.anilist_id in recent)
    if skipped:
        progress(
            f"skipping {skipped} title(s) {account.display} exported in the last "
            f"{account.repeat_days} days (--allow-repeats keeps them)"
        )
    fresh = [m for m in results if m.anilist_id not in recent][: query.limit]
    return _fill_chapters(fresh, chapters, progress)


def _drop_blocked(results: list[Manhwa], query: SearchQuery) -> list[Manhwa]:
    """The search's excluded genres/tags, enforced again here ignoring case: names saved while
    AniList was down are stored as typed, and AniList may compare them case-sensitively."""
    genres = {g.casefold() for g in query.exclude_genres}
    tags = {t.casefold() for t in query.exclude_tags}
    return [
        m
        for m in results
        if genres.isdisjoint(g.casefold() for g in m.genres)
        and tags.isdisjoint(t.casefold() for t in m.tags)
    ]


def merge_results(lists: list[list[Manhwa]], sort: Sort) -> list[Manhwa]:
    """Merge per-genre result lists without duplicates (first occurrence wins). SCORE and
    POPULARITY re-sort descending (unknown scores last); TRENDING interleaves the lists
    round-robin, because AniList's trending value isn't fetched."""
    if sort is Sort.TRENDING:
        ordered = [m for row in zip_longest(*lists) for m in row if m is not None]
    else:
        ordered = [m for results in lists for m in results]
    seen: set[int] = set()
    merged = []
    for m in ordered:
        if m.anilist_id not in seen:
            seen.add(m.anilist_id)
            merged.append(m)
    if sort is Sort.SCORE:
        merged.sort(key=lambda m: (m.score is None, -(m.score or 0)))
    elif sort is Sort.POPULARITY:
        merged.sort(key=lambda m: -m.popularity)
    return merged


def _fill_chapters(
    results: list[Manhwa], chapters: ChapterSource | None, progress: Callable[[str], None]
) -> list[Manhwa]:
    """Look up missing chapter counts on MangaUpdates; stop looking after the first failure."""
    if chapters is None:
        return results
    needs_lookup = sum(1 for m in results if m.chapter_count is None)
    if needs_lookup > 0:
        progress(f"looking up chapter counts for {needs_lookup} title(s) on MangaUpdates…")
    enriched = []
    lookups_failed = False
    for m in results:
        if not lookups_failed and m.chapter_count is None:
            try:
                m = m.model_copy(update={"latest_chapter": chapters.latest_chapter(m)})
            except MetadataError as e:
                progress(f"MangaUpdates unavailable, skipping chapter counts: {e}")
                lookups_failed = True
        enriched.append(m)
    return enriched
