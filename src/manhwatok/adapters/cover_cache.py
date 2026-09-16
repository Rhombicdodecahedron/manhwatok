"""Downloads AniList cover images once and keeps them under <data_dir>/covers/."""

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
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        """Close the HTTP client this source created (a client passed in stays open)."""
        if self._owns_client:
            self._client.close()

    def _path_for(self, manhwa: Manhwa) -> Path:
        ext = PurePosixPath(urlparse(manhwa.cover_url).path).suffix.lower()
        return self._dir / f"{manhwa.anilist_id}{ext if ext in _EXTENSIONS else '.jpg'}"

    def cached(self, manhwa: Manhwa) -> Path | None:
        """Local path of an already-downloaded cover, or None. Never downloads."""
        if not manhwa.cover_url:
            return None
        path = self._path_for(manhwa)
        return path if path.is_file() and path.stat().st_size > 0 else None

    def get(self, manhwa: Manhwa) -> Path:
        """Local path of the cover, downloading it on first use. Raises MetadataError on failure."""
        if not manhwa.cover_url:
            raise MetadataError(f"{manhwa.title}: AniList has no cover image")
        path = self._path_for(manhwa)
        if path.is_file() and path.stat().st_size > 0:
            return path
        try:
            resp = self._client.get(manhwa.cover_url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as e:
            raise MetadataError(f"cover download failed for {manhwa.title}: {e}") from e
        if resp.status_code >= 400 or not resp.content:
            raise MetadataError(
                f"cover download failed for {manhwa.title}: HTTP {resp.status_code}"
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".part")
        partial.write_bytes(resp.content)
        partial.replace(path)
        return path
