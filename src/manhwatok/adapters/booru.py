"""Fan art for a title from Danbooru, best-scored first.

Unlike AniList and MangaDex, a booru has no AniList id to pair on — only tag names. A loose name
match is therefore dangerous rather than merely imprecise: matching "The Return of the 8th Class
Mage" on substrings finds a Gundam series, and "I Am the Real One" finds a tag about clothing.
So a tag counts as this title only when it is a *copyright* tag whose name is exactly the
title's slug. That misses titles filed under another romanisation, which is the right way to be
wrong here — nothing is better than the wrong series' art on the slide.

What comes back is fan art by individual artists, not publisher art, so every option carries its
artist. Only ratings a booru calls general or sensitive are offered.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from manhwatok.adapters.anilist import USER_AGENT
from manhwatok.adapters.picture_download import download_picture
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Manhwa
from manhwatok.ports.art import ArtOption
from manhwatok.ports.cache import Cache

API = "https://danbooru.donmai.us"
COPYRIGHT = 3  # Danbooru tag category for a series
SAFE = ("g", "s")  # general, sensitive — never questionable or explicit
POST_LIMIT = 30


class BooruSource:
    def __init__(
        self,
        client: httpx.Client | None = None,
        cache: Cache | None = None,
        max_age: float = 30 * 24 * 3600,
        timeout: float = 20.0,
        limit: int = POST_LIMIT,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=API, timeout=timeout, follow_redirects=True
        )
        self._cache = cache
        self._max_age = max_age
        self._limit = limit

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def options(self, manhwa: Manhwa) -> list[ArtOption]:
        tag = self._tag(manhwa)
        if not tag:
            return []
        # Danbooru allows two search terms; `rating:` is free but `order:` is not, so the two
        # spent here are the title's tag and the ordering, and the rating is filtered below.
        posts = self._get("/posts.json", {"tags": f"{tag} order:score", "limit": self._limit})
        usable = [
            post
            for post in posts
            if post.get("file_url") and post.get("rating") in SAFE
        ]
        # `order:score` is asked for, but the ranking is redone here so that "best first" holds
        # whatever the search returns — the rating filter above already reshapes the list.
        usable.sort(key=lambda post: _score(post), reverse=True)
        return [ArtOption(label=_label(post), url=post["file_url"]) for post in usable]

    def fetch(self, option: ArtOption, into: Path) -> Path:
        return download_picture(option.url, into)

    def _tag(self, manhwa: Manhwa) -> str | None:
        key = f"booru:{manhwa.anilist_id}"
        if self._cache is not None:
            hit = self._cache.get(key, self._max_age)
            if hit is not None:
                return hit or None
        found = self._look_up(manhwa)
        if self._cache is not None:
            self._cache.put(key, found or "")
        return found

    def _look_up(self, manhwa: Manhwa) -> str | None:
        """The copyright tag named exactly after this title, or None."""
        for slug in _slugs(manhwa):
            for tag in self._get("/tags.json", {"search[name_matches]": slug, "limit": 10}):
                if tag.get("name") == slug and tag.get("category") == COPYRIGHT:
                    return slug
        return None

    def _get(self, path: str, params: dict) -> list[dict]:
        try:
            resp = self._client.get(path, params=params, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as e:
            raise MetadataError(f"booru request failed for {path}: {e}") from e
        if resp.status_code >= 400:
            raise MetadataError(f"booru returned HTTP {resp.status_code} for {path}")
        try:
            body = resp.json()
        except ValueError as e:
            raise MetadataError(f"booru sent something that isn't JSON for {path}: {e}") from e
        return body if isinstance(body, list) else []


def _slugs(manhwa: Manhwa) -> list[str]:
    names = [_slug(manhwa.title)]
    romaji = _slug(manhwa.romaji)
    if romaji and romaji not in names:
        names.append(romaji)
    return [n for n in names if n]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def _score(post: dict) -> int:
    try:
        return int(post.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def _label(post: dict) -> str:
    size = f"{post.get('image_width') or '?'}x{post.get('image_height') or '?'}"
    label = f"★ {post.get('score', 0)}  {size}"
    artist = (post.get("tag_string_artist") or "").split(" ")[0].strip()
    return f"{label}  by {artist}" if artist else label
