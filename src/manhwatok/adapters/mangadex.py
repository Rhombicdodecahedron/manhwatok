"""MangaDex: volume covers for titles AniList only has one cover of, and chapter pages.

MangaDex records carry the AniList id in `links.al`, so a title search plus that check is an
exact match rather than a guess. What comes back is official volume art — often a dozen or more
pictures for a title the rest of manhwatok knows by a single cover — and, for a chapter post,
the pages of a chapter itself.

MangaDex allows roughly five requests a second per address, and a chapter is one request per
page, so every request here is spaced and a 429 is waited out rather than retried blindly.
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from manhwatok.adapters.anilist import USER_AGENT
from manhwatok.adapters.picture_download import download_picture, stream_to_file
from manhwatok.domain.chapter import chapter_sort_key
from manhwatok.domain.errors import ManhwatokError, MetadataError
from manhwatok.domain.models import Manhwa
from manhwatok.ports.art import ArtOption
from manhwatok.ports.cache import Cache
from manhwatok.ports.chapters import ChapterInfo

API = "https://api.mangadex.org"
UPLOADS = "https://uploads.mangadex.org/covers"
SEARCH_LIMIT = 8
COVER_LIMIT = 100
FEED_LIMIT = 100  # the most chapters one feed request returns
FEED_MAX = 10_000  # MangaDex refuses offsets past this
GAP = 0.25  # seconds between requests: its published limit is about five a second
MAX_WAIT = 120.0  # the longest a rate-limited request waits before giving up
MAX_PAGE_BYTES = 40 * 1024 * 1024  # a webtoon page is a few MB; this is the absurd-file guard
RATINGS = ["safe", "suggestive", "erotica"]
_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _retry_after(resp: httpx.Response) -> float:
    """How long MangaDex asked us to wait, or a second when it didn't say."""
    try:
        return max(1.0, float(resp.headers.get("Retry-After", "1")))
    except ValueError:
        return 1.0


class _MangaDexApi:
    """The client, the AniList pairing and the request spacing both sources share."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        cache: Cache | None = None,
        max_age: float = 30 * 24 * 3600,
        timeout: float = 20.0,
        gap: float = GAP,
        max_wait: float = MAX_WAIT,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=API, timeout=timeout, follow_redirects=True
        )
        self._cache = cache
        self._max_age = max_age
        self._gap = gap
        self._max_wait = max_wait
        self._clock = clock
        self._sleep = sleep
        self._last = 0.0

    def close(self) -> None:
        """Close the HTTP client this source created (a client passed in stays open)."""
        if self._owns_client:
            self._client.close()

    def _wait_turn(self) -> None:
        """Keep at least `gap` between requests, counted from the last one."""
        if self._last:
            since = self._clock() - self._last
            if since < self._gap:
                self._sleep(self._gap - since)
        self._last = self._clock()

    def _request(self, path: str, params: dict | None = None) -> httpx.Response:
        """One request, spaced, waiting out a 429 for as long as it asks (up to `max_wait`)."""
        waited = 0.0
        while True:
            self._wait_turn()
            try:
                resp = self._client.get(
                    path, params=params, headers={"User-Agent": USER_AGENT}
                )
            except httpx.HTTPError as e:
                raise MetadataError(f"MangaDex request failed for {path}: {e}") from e
            if resp.status_code != 429:
                return resp
            after = _retry_after(resp)
            if waited + after > self._max_wait:
                raise MetadataError(
                    f"MangaDex rate limit is still on after {round(waited)}s — try again later"
                )
            waited += after
            self._sleep(after)

    def _json(self, path: str, params: dict | None = None) -> dict:
        """A whole JSON body: /at-home/server is not wrapped in `data`."""
        resp = self._request(path, params)
        if resp.status_code >= 400:
            raise MetadataError(f"MangaDex returned HTTP {resp.status_code} for {path}")
        try:
            body = resp.json()
        except ValueError as e:
            raise MetadataError(f"MangaDex sent something that isn't JSON for {path}: {e}") from e
        return body if isinstance(body, dict) else {}

    def _get(self, path: str, params: dict) -> list[dict]:
        return self._json(path, params).get("data") or []

    def _get_all(self, path: str, params: dict, limit: int = FEED_LIMIT) -> list[dict]:
        """Every page of a paged endpoint, following the `total` the envelope reports."""
        found: list[dict] = []
        offset = 0
        while offset < FEED_MAX:
            body = self._json(path, {**params, "limit": limit, "offset": offset})
            page = body.get("data") or []
            found += page
            total = body.get("total")
            offset += limit
            if not page or not isinstance(total, int) or offset >= total:
                break
        return found

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


class MangaDexSource(_MangaDexApi):
    """Volume covers, offered as art for a title's slide."""

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


class MangaDexChapters(_MangaDexApi):
    """A title's chapters, and the pages of one, kept under `pages_dir/<chapter id>/`.

    A downloaded page is never fetched twice: the file being there and non-empty is the cache,
    as it is for covers. Chapter pages are large, so they stream to disk rather than through
    memory."""

    def __init__(
        self,
        pages_dir: Path,
        client: httpx.Client | None = None,
        cache: Cache | None = None,
        max_age: float = 30 * 24 * 3600,
        timeout: float = 20.0,
        gap: float = GAP,
        max_wait: float = MAX_WAIT,
        max_page_bytes: int = MAX_PAGE_BYTES,
        data_saver: bool = False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(client, cache, max_age, timeout, gap, max_wait, clock, sleep)
        self._dir = pages_dir
        self._max_page_bytes = max_page_bytes
        # Data-saver pages are re-compressed; on a chapter post the lettering is the content,
        # so the full-size pages are worth their bytes.
        self._data_saver = data_saver

    def chapters(self, manhwa: Manhwa, language: str = "en") -> list[ChapterInfo]:
        manga_id = self._manga_id(manhwa)
        if not manga_id:
            return []
        try:
            entries = self._get_all(
                f"/manga/{manga_id}/feed",
                {
                    "translatedLanguage[]": [language],
                    "order[chapter]": "asc",
                    "contentRating[]": RATINGS,
                    "includeExternalUrl": 0,
                },
            )
        except MetadataError as e:
            raise MetadataError(f"MangaDex could not list chapters of {manhwa.title}: {e}") from e
        return pick_chapters(entries, language)

    def pages(
        self, chapter: ChapterInfo, progress: Callable[[str], None] | None = None
    ) -> list[Path]:
        """The chapter's pages in reading order, downloading whatever isn't already here."""
        body = self._json(f"/at-home/server/{chapter.chapter_id}")
        base = body.get("baseUrl") or ""
        block = body.get("chapter") or {}
        names = block.get("dataSaver" if self._data_saver else "data") or []
        if not base or not names:
            raise MetadataError(f"MangaDex serves no pages for chapter {chapter.number}")
        folder = self._dir / chapter.chapter_id
        kind = "data-saver" if self._data_saver else "data"
        found = []
        for n, name in enumerate(names, 1):
            path = folder / f"{n:02d}{_suffix(name)}"
            if not _usable(path):
                if progress:
                    progress(f"chapter {chapter.number}: page {n} of {len(names)}")
                folder.mkdir(parents=True, exist_ok=True)
                self._wait_turn()
                try:
                    stream_to_file(
                        f"{base}/{kind}/{block.get('hash', '')}/{name}",
                        path,
                        self._client,
                        headers={"User-Agent": USER_AGENT},
                        max_bytes=self._max_page_bytes,
                    )
                except ManhwatokError as e:
                    raise MetadataError(
                        f"chapter {chapter.number}: page {n} could not be downloaded — {e}"
                    ) from e
            found.append(path)
        return found

    def cached_pages(self, chapter: ChapterInfo) -> list[Path]:
        """What is already on disk, in order; nothing unless the chapter is whole."""
        folder = self._dir / chapter.chapter_id
        found = sorted(p for p in folder.glob("[0-9][0-9].*") if _usable(p))
        if chapter.pages and len(found) < chapter.pages:
            return []
        return found


def pick_chapters(entries: list[dict], language: str) -> list[ChapterInfo]:
    """One chapter per number, in chapter order. Several groups translate the same chapter, so
    the fullest translation wins; a chapter hosted elsewhere or with no pages has nothing to
    download and is left out."""
    best: dict[str, ChapterInfo] = {}
    for entry in entries:
        attributes = entry.get("attributes") or {}
        pages = attributes.get("pages") or 0
        if attributes.get("externalUrl") or not isinstance(pages, int) or pages <= 0:
            continue
        if (attributes.get("translatedLanguage") or "") != language:
            continue
        number = (attributes.get("chapter") or "").strip()
        found = ChapterInfo(
            chapter_id=entry.get("id") or "",
            number=number,
            title=(attributes.get("title") or "").strip(),
            language=language,
            pages=pages,
        )
        if not found.chapter_id:
            continue
        kept = best.get(number)
        if kept is None or found.pages > kept.pages:
            best[number] = found
    return sorted(best.values(), key=lambda c: chapter_sort_key(c.number))


def _usable(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _suffix(name: str) -> str:
    ext = Path(urlparse(name).path).suffix.lower()
    return ext if ext in _EXTENSIONS else ".jpg"


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
