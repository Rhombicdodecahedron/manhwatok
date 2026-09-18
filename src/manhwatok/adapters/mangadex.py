"""Volume covers from MangaDex, for titles AniList only has one cover of.

MangaDex records carry the AniList id in `links.al`, so a title search plus that check is an
exact match rather than a guess. What comes back is official volume art — often a dozen or more
pictures for a title the rest of manhwatok knows by a single cover.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import httpx

from manhwatok.adapters.anilist import USER_AGENT
from manhwatok.adapters.picture_download import download_picture
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Manhwa
from manhwatok.ports.art import ArtOption
from manhwatok.ports.cache import Cache

API = "https://api.mangadex.org"
UPLOADS = "https://uploads.mangadex.org/covers"
SEARCH_LIMIT = 8
COVER_LIMIT = 100
RATINGS = ["safe", "suggestive", "erotica"]


class MangaDexSource:
    def __init__(
        self,
        client: httpx.Client | None = None,
        cache: Cache | None = None,
        max_age: float = 30 * 24 * 3600,
        timeout: float = 20.0,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=API, timeout=timeout, follow_redirects=True
        )
        self._cache = cache
        self._max_age = max_age

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def options(self, manhwa: Manhwa, tag: str | None = None) -> list[ArtOption]:
        """`tag` is ignored: a volume cover is described by its volume, not by what is on it."""
        manga_id = self._manga_id(manhwa)
        if not manga_id:
            return []
        covers = self._get("/cover", {"manga[]": manga_id, "limit": COVER_LIMIT})
        found = []
        for cover in covers:
            attributes = cover.get("attributes") or {}
            name = attributes.get("fileName")
            if not name:
                continue
            volume = (attributes.get("volume") or "").strip()
            locale = (attributes.get("locale") or "").strip()
            found.append((volume, locale, f"{UPLOADS}/{manga_id}/{name}"))
        found.sort(key=lambda c: (_volume_key(c[0]), c[1]))
        # MangaDex keeps one cover per volume *per language*, so a bare "vol. 3" can appear
        # several times. Name the language only where it is what tells two of them apart.
        crowded = {v for v, count in Counter(volume for volume, _, _ in found).items() if count > 1}
        return [
            ArtOption(label=_label(volume, locale, volume in crowded), url=url)
            for volume, locale, url in found
        ]

    def fetch(self, option: ArtOption, into: Path) -> Path:
        return download_picture(option.url, into)

    def _manga_id(self, manhwa: Manhwa) -> str | None:
        """The MangaDex id whose AniList link is this title's, or None. Cached: the answer is a
        pairing of two catalogues, which does not change once made."""
        key = f"mangadex:{manhwa.anilist_id}"
        if self._cache is not None:
            hit = self._cache.get(key, self._max_age)
            if hit is not None:
                return hit or None
        found = self._search(manhwa)
        if self._cache is not None:
            self._cache.put(key, found or "")
        return found

    def _search(self, manhwa: Manhwa) -> str | None:
        for title in _titles(manhwa):
            for entry in self._get(
                "/manga", {"title": title, "limit": SEARCH_LIMIT, "contentRating[]": RATINGS}
            ):
                links = (entry.get("attributes") or {}).get("links") or {}
                if str(links.get("al") or "") == str(manhwa.anilist_id):
                    return entry.get("id")
        return None

    def _get(self, path: str, params: dict) -> list[dict]:
        try:
            resp = self._client.get(path, params=params, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as e:
            raise MetadataError(f"MangaDex request failed for {path}: {e}") from e
        if resp.status_code >= 400:
            raise MetadataError(f"MangaDex returned HTTP {resp.status_code} for {path}")
        try:
            return resp.json().get("data") or []
        except ValueError as e:
            raise MetadataError(f"MangaDex sent something that isn't JSON for {path}: {e}") from e


def _titles(manhwa: Manhwa) -> list[str]:
    """The title to search under, then the romaji one when it differs — AniList's English and
    MangaDex's preferred title disagree often enough to be worth the second try."""
    names = [manhwa.title]
    if manhwa.romaji and manhwa.romaji != manhwa.title:
        names.append(manhwa.romaji)
    return names


def _label(volume: str, locale: str, needs_locale: bool) -> str:
    name = f"vol. {volume}" if volume else "cover"
    return f"{name} ({locale})" if needs_locale and locale else name


def _volume_key(volume: str) -> tuple[int, float, str]:
    """Sort volumes by number, keeping unnumbered covers last."""
    if not volume:
        return (1, 0.0, "")
    try:
        return (0, float(volume), "")
    except ValueError:
        return (0, float("inf"), volume)
