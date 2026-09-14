"""Caches chapter lookups (hits and misses) so repeated suggests don't re-query MangaUpdates."""

from __future__ import annotations

import json

from manhwatok.domain.errors import CacheError
from manhwatok.domain.models import Manhwa
from manhwatok.ports.cache import Cache
from manhwatok.ports.metadata import ChapterSource


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
            return json.loads(hit)
        value = self._inner.latest_chapter(manhwa)
        try:
            self._cache.put(key, json.dumps(value))
        except CacheError:
            pass
        return value
