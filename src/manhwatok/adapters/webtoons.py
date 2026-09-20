"""Chapters from webtoons.com: the publisher's own English, where MangaDex has gaps.

MangaDex carries what fan groups translated, which for a licensed title is often the middle of
the run — The Boxer starts at chapter 12 there. WEBTOON carries the official translation from
episode 1, so it is the better source where it has the title at all. What it does not carry is
the newest episodes of an ongoing series, which sit behind Fast Pass: those have no strips in
the viewer, and are reported as not free rather than downloaded empty.

There is no public API. The search page is plain HTML with the series id in it, the mobile site
answers a JSON episode list, and a viewer page lists the strips of one episode. The strips come
from Naver's CDN, which answers 403 without the site as referer.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from manhwatok.adapters.picture_download import stream_to_file
from manhwatok.domain.errors import ManhwatokError, MetadataError
from manhwatok.domain.models import Manhwa
from manhwatok.ports.cache import Cache
from manhwatok.ports.chapters import ChapterInfo

SITE = "https://www.webtoons.com"
MOBILE = "https://m.webtoons.com"
VIEWER_REFERER = "https://www.webtoons.com/"
# WEBTOON's own pages, asked for as a browser would: the site answers a scripted client with a
# consent wall rather than the page.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
PAGE_SIZE = 100
GAP = 0.5  # seconds between requests; WEBTOON is a website, not an API
MAX_PAGE_BYTES = 40 * 1024 * 1024
LANGUAGE = "en"

# A search result: the series id on the link, then its name in the card's own text. WEBTOON
# has used both <p class="subj"> and <strong class="title"> for that name.
_CARD = re.compile(
    r'data-title-no="(\d+)"[^>]*>.*?<(?:p|strong) class="(?:subj|title)">([^<]+)</(?:p|strong)>',
    re.S,
)
_STRIP = re.compile(r'class="_images"[^>]*data-url="([^"]+)"')
_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


class WebtoonsChapters:
    """A title's episodes on webtoons.com, and the strips of one, kept under `pages_dir`."""

    def __init__(
        self,
        pages_dir: Path,
        client: httpx.Client | None = None,
        cache: Cache | None = None,
        max_age: float = 30 * 24 * 3600,
        timeout: float = 20.0,
        gap: float = GAP,
        page_size: int = PAGE_SIZE,
        max_page_bytes: int = MAX_PAGE_BYTES,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._dir = pages_dir
        self._cache = cache
        self._max_age = max_age
        self._gap = gap
        self._page_size = page_size
        self._max_page_bytes = max_page_bytes
        self._clock = clock
        self._sleep = sleep
        self._last = 0.0

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def chapters(self, manhwa: Manhwa, language: str = LANGUAGE) -> list[ChapterInfo]:
        """Every episode WEBTOON lists for the title, oldest first. English only: this is the
        English site, and a chapter post is read, not just looked at."""
        if language != LANGUAGE:
            return []
        series = self._series_id(manhwa)
        if not series:
            return []
        found: list[ChapterInfo] = []
        start = 0
        while True:
            body = self._json(
                f"{MOBILE}/api/v1/webtoon/{series}/episodes",
                {"pageSize": self._page_size, "startIndex": start},
                manhwa.title,
            )
            episodes = ((body.get("result") or {}).get("episodeList")) or []
            for episode in episodes:
                number = episode.get("episodeNo")
                if not isinstance(number, int):
                    continue
                found.append(
                    ChapterInfo(
                        chapter_id=f"{series}:{number}",
                        number=str(number),
                        title=(episode.get("episodeTitle") or "").strip(),
                        language=LANGUAGE,
                        pages=0,  # the strips are only counted once the viewer is opened
                    )
                )
            start += self._page_size
            if len(episodes) < self._page_size:
                break
        return sorted(found, key=lambda c: int(c.number))

    def other_languages(
        self, manhwa: Manhwa, before: str, language: str = LANGUAGE
    ) -> dict[str, int]:
        """Nothing to offer: this is the English site, and each language is its own."""
        return {}

    def pages(
        self, chapter: ChapterInfo, progress: Callable[[str], None] | None = None
    ) -> list[Path]:
        """The episode's strips in reading order, downloading whatever isn't already here."""
        series, _, episode = chapter.chapter_id.partition(":")
        page = self._text(
            f"{SITE}/en/x/x/x/viewer",
            {"title_no": series, "episode_no": episode},
            f"episode {chapter.number}",
        )
        strips = _STRIP.findall(page)
        if not strips:
            raise MetadataError(
                f"episode {chapter.number} is not free on WEBTOON — Fast Pass episodes have no "
                "strips to download"
            )
        folder = self._dir / f"webtoons-{series}-{episode}"
        found = []
        for n, url in enumerate(strips, 1):
            path = folder / f"{n:02d}{_suffix(url)}"
            if not _usable(path):
                if progress:
                    progress(f"episode {chapter.number}: strip {n} of {len(strips)}")
                folder.mkdir(parents=True, exist_ok=True)
                self._wait_turn()
                try:
                    stream_to_file(
                        url,
                        path,
                        self._client,
                        headers={"User-Agent": USER_AGENT, "Referer": VIEWER_REFERER},
                        max_bytes=self._max_page_bytes,
                    )
                except ManhwatokError as e:
                    raise MetadataError(
                        f"episode {chapter.number}: strip {n} could not be downloaded — {e}"
                    ) from e
            found.append(path)
        return found

    def cached_pages(self, chapter: ChapterInfo) -> list[Path]:
        series, _, episode = chapter.chapter_id.partition(":")
        folder = self._dir / f"webtoons-{series}-{episode}"
        return sorted(p for p in folder.glob("[0-9][0-9].*") if _usable(p))

    # --- the site ------------------------------------------------------------------------

    def _series_id(self, manhwa: Manhwa) -> str | None:
        """WEBTOON's id for the title, by name. Cached: it is a pairing of two catalogues,
        which does not change once made."""
        key = f"webtoons:{manhwa.anilist_id}"
        if self._cache is not None:
            hit = self._cache.get(key, self._max_age)
            if hit is not None:
                return hit or None
        found = self._search(manhwa)
        if self._cache is not None:
            self._cache.put(key, found or "")
        return found

    def _search(self, manhwa: Manhwa) -> str | None:
        wanted = {_norm(manhwa.title), _norm(manhwa.romaji)} - {""}
        for name in (manhwa.title, manhwa.romaji):
            if not name.strip():
                continue
            page = self._text(f"{SITE}/en/search", {"keyword": name}, manhwa.title)
            for series, found in _CARD.findall(page):
                if _norm(found) in wanted:
                    return series
        return None

    def _wait_turn(self) -> None:
        if self._last:
            since = self._clock() - self._last
            if since < self._gap:
                self._sleep(self._gap - since)
        self._last = self._clock()

    def _get(self, url: str, params: dict, about: str) -> httpx.Response:
        self._wait_turn()
        try:
            resp = self._client.get(url, params=params, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as e:
            raise MetadataError(f"WEBTOON request failed for {about}: {e}") from e
        if resp.status_code >= 400:
            raise MetadataError(f"WEBTOON returned HTTP {resp.status_code} for {about}")
        return resp

    def _text(self, url: str, params: dict, about: str) -> str:
        return self._get(url, params, about).text

    def _json(self, url: str, params: dict, about: str) -> dict:
        resp = self._get(url, params, about)
        try:
            body = resp.json()
        except ValueError as e:
            raise MetadataError(f"WEBTOON sent something that isn't JSON for {about}: {e}") from e
        return body if isinstance(body, dict) else {}


def _usable(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _suffix(url: str) -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in _EXTENSIONS:
        return ext
    # WEBTOON's strip urls often carry the type in the folder instead: .../..._JPEG/...
    kind = re.search(r"_(JPEG|JPG|PNG|GIF)/", url, re.I)
    return f".{kind.group(1).lower().replace('jpeg', 'jpg')}" if kind else ".jpg"
