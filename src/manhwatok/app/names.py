"""Check genre/tag names against AniList's lists (cached 24 h) so typos fail when an account or
theme is saved, not later as an empty search."""

from __future__ import annotations

import difflib
import json
from typing import Callable, Protocol

from manhwatok.domain.errors import CacheError, InvalidName, MetadataError
from manhwatok.domain.text import clean_names
from manhwatok.ports.cache import Cache
from manhwatok.ports.metadata import MetadataSource

NAMES_MAX_AGE = 24 * 3600


class NameCheck(Protocol):
    def genres(self, names: list[str]) -> list[str]:
        """AniList's spelling of each genre; raises InvalidName for unknown ones."""
        ...

    def tags(self, names: list[str]) -> list[str]: ...


def canonical_names(names: list[str], known: list[str], kind: str) -> list[str]:
    """Map each name case-insensitively onto `known`; unknown names raise InvalidName with up to
    three close matches."""
    by_fold = {k.casefold(): k for k in known}
    out = []
    for name in names:
        hit = by_fold.get(name.casefold())
        if hit is None:
            close = difflib.get_close_matches(name.casefold(), list(by_fold), n=3)
            if close:
                hint = "did you mean " + ", ".join(by_fold[c] for c in close) + "?"
            elif kind == "genre":
                hint = "AniList genres: " + ", ".join(known)
            else:
                hint = "see `manhwatok tags`"
            raise InvalidName(f"unknown {kind} {name!r} — {hint}")
        out.append(hit)
    return clean_names(out)


def _name_list(text: str) -> list[str] | None:
    """A cached name list, or None if the cached text is corrupt (then it's fetched again and
    overwritten)."""
    try:
        value = json.loads(text)
    except ValueError:
        return None
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    return None


class AniListNames:
    """NameCheck backed by AniList's genre and tag lists, cached in the store. If AniList can't
    be reached, warns once and accepts names as typed."""

    def __init__(self, metadata: MetadataSource, cache: Cache, warn: Callable[[str], None]) -> None:
        self._metadata = metadata
        self._cache = cache
        self._warn = warn
        self._down = False

    def genres(self, names: list[str]) -> list[str]:
        return self._check(names, "genre", self._metadata.list_genres)

    def tags(self, names: list[str]) -> list[str]:
        return self._check(names, "tag", lambda: [t.name for t in self._metadata.list_tags()])

    def _check(self, names: list[str], kind: str, fetch: Callable[[], list[str]]) -> list[str]:
        if not names:
            return []
        known = self._known(f"anilist:{kind}s", fetch)
        return names if known is None else canonical_names(names, known, kind)

    def _known(self, key: str, fetch: Callable[[], list[str]]) -> list[str] | None:
        try:
            hit = self._cache.get(key, NAMES_MAX_AGE)
        except CacheError:
            hit = None
        cached = _name_list(hit) if hit is not None else None
        if cached is not None:
            return cached
        if self._down:
            return None
        try:
            names = fetch()
        except MetadataError as e:
            self._down = True
            self._warn(f"warning: couldn't check names against AniList ({e}) — saved as typed")
            return None
        try:
            self._cache.put(key, json.dumps(names))
        except CacheError:
            pass
        return names
