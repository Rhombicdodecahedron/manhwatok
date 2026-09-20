"""Chapters from Asura Scans: its own translations, usually the whole run from chapter 1.

Where MangaDex carries whatever groups uploaded and WEBTOON carries licensed originals, Asura
translates ongoing action manhwa itself and keeps every chapter of what it picks up. That makes
it the source that has a complete early run when the other two don't.

The site itself is a JavaScript application behind Cloudflare, but the application talks to a
plain JSON API, and so does this: search for the series, list its chapters, read one chapter's
page urls. Asura has changed domain repeatedly (asurascans.com → asura.gg → asuracomic.net →
asurascans.com again), so the host is a constant here and the day it moves again, this is the
line to change.

Its newest chapters are early access — paid — and those are left out rather than downloaded
empty.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from manhwatok.adapters.picture_download import stream_to_file
from manhwatok.domain.chapter import chapter_sort_key
from manhwatok.domain.errors import ManhwatokError, MetadataError
from manhwatok.domain.models import Manhwa
from manhwatok.ports.cache import Cache
from manhwatok.ports.chapters import ChapterInfo

API = "https://api.asurascans.com"
SITE = "https://asurascans.com/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
GAP = 0.4  # seconds between requests: a small site, not an API with a published budget
MAX_PAGE_BYTES = 40 * 1024 * 1024
LANGUAGE = "en"
_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


class AsuraChapters:
    """A title's chapters on Asura, and the pages of one, kept under `pages_dir`."""

    def __init__(
        self,
        pages_dir: Path,
        client: httpx.Client | None = None,
        cache: Cache | None = None,
        max_age: float = 30 * 24 * 3600,
        timeout: float = 20.0,
        gap: float = GAP,
        max_page_bytes: int = MAX_PAGE_BYTES,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=API, timeout=timeout, follow_redirects=True
        )
        self._dir = pages_dir
        self._cache = cache
        self._max_age = max_age
        self._gap = gap
        self._max_page_bytes = max_page_bytes
        self._clock = clock
        self._sleep = sleep
        self._last = 0.0

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def chapters(self, manhwa: Manhwa, language: str = LANGUAGE) -> list[ChapterInfo]:
        """Every free chapter Asura has for the title, in chapter-number order."""
        if language != LANGUAGE:
            return []  # Asura translates into English
        slug = self._series(manhwa)
        if not slug:
            return []
        listed = self._json(f"/api/series/{slug}/chapters", manhwa.title).get("data") or []
        found = []
        for entry in listed:
            number = entry.get("number")
            chapter_slug = entry.get("slug")
            if number is None or not chapter_slug or entry.get("is_premium"):
                continue  # early access chapters are paid, and serve no pages
            found.append(
                ChapterInfo(
                    chapter_id=f"{slug}/{chapter_slug}",
                    number=_number(number),
                    title=(entry.get("title") or "").strip(),
                    language=LANGUAGE,
                    pages=int(entry.get("page_count") or 0),
                )
            )
        return sorted(found, key=lambda c: chapter_sort_key(c.number))

    def other_languages(
        self, manhwa: Manhwa, before: str, language: str = LANGUAGE
    ) -> dict[str, int]:
        """Nothing to offer: Asura publishes its own English translation and no other."""
        return {}

    def pages(
        self, chapter: ChapterInfo, progress: Callable[[str], None] | None = None
    ) -> list[Path]:
        """The chapter's pages in reading order, downloading whatever isn't already here."""
        series, _, chapter_slug = chapter.chapter_id.partition("/")
        body = self._json(
            f"/api/series/{series}/chapters/{chapter_slug}", f"chapter {chapter.number}"
        )
        found = ((body.get("data") or {}).get("chapter")) or {}
        if found.get("is_premium"):
            raise MetadataError(
                f"chapter {chapter.number} is early access on Asura — paid chapters serve no pages"
            )
        urls = [page.get("url") for page in (found.get("pages") or []) if page.get("url")]
        if not urls:
            raise MetadataError(f"Asura serves no pages for chapter {chapter.number}")
        folder = self._dir / f"asura-{chapter.chapter_id.replace('/', '-')}"
        kept = []
        for n, url in enumerate(urls, 1):
            path = folder / f"{n:02d}{_suffix(url)}"
            if not _usable(path):
                if progress:
                    progress(f"chapter {chapter.number}: page {n} of {len(urls)}")
                folder.mkdir(parents=True, exist_ok=True)
                self._wait_turn()
                try:
                    stream_to_file(
                        url,
                        path,
                        self._client,
                        headers={"User-Agent": USER_AGENT, "Referer": SITE},
                        max_bytes=self._max_page_bytes,
                    )
                except ManhwatokError as e:
                    raise MetadataError(
                        f"chapter {chapter.number}: page {n} could not be downloaded — {e}"
                    ) from e
            kept.append(path)
        return kept

    def cached_pages(self, chapter: ChapterInfo) -> list[Path]:
        folder = self._dir / f"asura-{chapter.chapter_id.replace('/', '-')}"
        found = sorted(p for p in folder.glob("[0-9][0-9].*") if _usable(p))
        if chapter.pages and len(found) < chapter.pages:
            return []
        return found

    # --- the site ------------------------------------------------------------------------

    def _series(self, manhwa: Manhwa) -> str | None:
        """Asura's slug for the title, by name. Cached: a pairing of two catalogues, which
        does not change once made."""
        key = f"asura:{manhwa.anilist_id}"
        if self._cache is not None:
            hit = self._cache.get(key, self._max_age)
            if hit is not None:
                return hit or None
        found = self._search(manhwa)
        if self._cache is not None:
            self._cache.put(key, found or "")
        return found

    def _search(self, manhwa: Manhwa) -> str | None:
        """Asura files a Korean title under whichever name its translators used, so its own
        alternative titles are matched as well as its main one."""
        wanted = {_norm(n) for n in (manhwa.title, manhwa.romaji, *(manhwa.synonyms or []))}
        wanted -= {""}
        for name in (manhwa.title, manhwa.romaji):
            if not name.strip():
                continue
            listed = self._json("/api/series", manhwa.title, {"search": name}).get("data") or []
            for entry in listed:
                names = [entry.get("title") or "", *(entry.get("alt_titles") or [])]
                if any(_norm(found) in wanted for found in names) and entry.get("slug"):
                    return entry["slug"]
        return None

    def _wait_turn(self) -> None:
        if self._last:
            since = self._clock() - self._last
            if since < self._gap:
                self._sleep(self._gap - since)
        self._last = self._clock()

    def _json(self, path: str, about: str, params: dict | None = None) -> dict:
        self._wait_turn()
        try:
            resp = self._client.get(
                path, params=params, headers={"User-Agent": USER_AGENT, "Referer": SITE}
            )
        except httpx.HTTPError as e:
            raise MetadataError(f"Asura request failed for {about}: {e}") from e
        if resp.status_code >= 400:
            raise MetadataError(f"Asura returned HTTP {resp.status_code} for {about}")
        try:
            body = resp.json()
        except ValueError as e:
            raise MetadataError(f"Asura sent something that isn't JSON for {about}: {e}") from e
        return body if isinstance(body, dict) else {}


def _number(value) -> str:
    """Asura numbers chapters as numbers, and half-chapters as decimals."""
    number = float(value)
    return str(int(number)) if number == int(number) else str(number)


def _usable(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _suffix(url: str) -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    return ext if ext in _EXTENSIONS else ".jpg"
