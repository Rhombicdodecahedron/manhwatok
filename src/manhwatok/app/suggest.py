"""Suggest manhwa for a theme: AniList search, then fill in missing chapter counts."""

from __future__ import annotations

from typing import Callable

from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Manhwa, SearchQuery
from manhwatok.ports.metadata import ChapterSource, MetadataSource


def _noop(_: str) -> None:
    pass


def suggest_titles(
    query: SearchQuery,
    metadata: MetadataSource,
    chapters: ChapterSource | None = None,
    progress: Callable[[str], None] = _noop,
) -> list[Manhwa]:
    results = metadata.search(query)
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
