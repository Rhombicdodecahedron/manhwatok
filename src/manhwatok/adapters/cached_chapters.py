"""Caches chapter lookups (hits and misses) so repeated suggests don't re-query MangaUpdates."""

from __future__ import annotations

import json

from manhwatok.domain.errors import CacheError
from manhwatok.domain.models import Manhwa
from manhwatok.ports.cache import Cache
from manhwatok.ports.metadata import ChapterSource


def _decode(hit: str) -> tuple[bool, int | None]:
    """(True, count) for a well-formed cached lookup (None: not found on MangaUpdates),
    (False, None) for a corrupt entry."""
    try:
        value = json.loads(hit)
    except ValueError:
        return False, None
    if value is None or type(value) is int:  # not bool, float, str, list…
        return True, value
    return False, None


class CachedChapterSource:
    def __init__(self, inner: ChapterSource, cache: Cache, max_age: float) -> None:
        self._inner = inner
        self._cache = cache
        self._max_age = max_age

    def latest_chapter(self, manhwa: Manhwa) -> int | None:
        key = f"latest_chapter:{manhwa.anilist_id}"
        try:
            hit = self._cache.get(key, self._max_age)
        except CacheError:
            hit = None
        if hit is not None:
            ok, cached = _decode(hit)
            if ok:
                return cached
            # a corrupt entry is a miss: fetch again and overwrite it
        value = self._inner.latest_chapter(manhwa)
        try:
            self._cache.put(key, json.dumps(value))
        except CacheError:
            pass
        return value
