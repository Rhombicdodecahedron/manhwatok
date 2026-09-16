"""Downloads AniList cover and banner images once and keeps them under <data_dir>/covers/."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import httpx

from manhwatok.adapters.anilist import USER_AGENT
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Manhwa

_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class CoverCache:
    def __init__(
        self, covers_dir: Path, client: httpx.Client | None = None, timeout: float = 20.0
    ) -> None:
        self._dir = covers_dir
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def _path_for(self, manhwa: Manhwa, url: str, suffix: str = "") -> Path:
        ext = PurePosixPath(urlparse(url).path).suffix.lower()
        return self._dir / f"{manhwa.anilist_id}{suffix}{ext if ext in _EXTENSIONS else '.jpg'}"

    @staticmethod
    def _usable(path: Path) -> bool:
        return path.is_file() and path.stat().st_size > 0

    def _cached(self, manhwa: Manhwa, url: str, suffix: str) -> Path | None:
        if not url:
            return None
        path = self._path_for(manhwa, url, suffix)
        return path if self._usable(path) else None

    def _get(self, manhwa: Manhwa, url: str, suffix: str, kind: str) -> Path:
        if not url:
            raise MetadataError(f"{manhwa.title}: AniList has no {kind} image")
        path = self._path_for(manhwa, url, suffix)
        if self._usable(path):
            return path
        try:
            resp = self._client.get(url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as e:
            raise MetadataError(f"{kind} download failed for {manhwa.title}: {e}") from e
        if resp.status_code >= 400 or not resp.content:
            raise MetadataError(
                f"{kind} download failed for {manhwa.title}: HTTP {resp.status_code}"
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".part")
        partial.write_bytes(resp.content)
        partial.replace(path)
        return path

    def cached(self, manhwa: Manhwa) -> Path | None:
        """Local path of an already-downloaded cover, or None. Never downloads."""
        return self._cached(manhwa, manhwa.cover_url, "")

    def get(self, manhwa: Manhwa) -> Path:
        """Local path of the cover, downloading it on first use. Raises MetadataError on failure."""
        return self._get(manhwa, manhwa.cover_url, "", "cover")

    def cached_banner(self, manhwa: Manhwa) -> Path | None:
        """Local path of an already-downloaded banner, or None. Never downloads."""
        return self._cached(manhwa, manhwa.banner_url, "-banner")

    def get_banner(self, manhwa: Manhwa) -> Path:
        """Local path of the banner, downloading it on first use. Raises MetadataError on
        failure. Only about half of manhwa have a banner at all — callers check banner_url."""
        return self._get(manhwa, manhwa.banner_url, "-banner", "banner")
