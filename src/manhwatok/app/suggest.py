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
    enriched = []
    for m in results:
        if m.chapter_count is None:
            try:
                m = m.model_copy(update={"latest_chapter": chapters.latest_chapter(m)})
            except MetadataError as e:
                progress(f"no chapter count for {m.title}: {e}")
        enriched.append(m)
    return enriched
