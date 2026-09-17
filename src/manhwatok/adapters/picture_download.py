"""Fetches a picture the user linked to, so `art` takes a URL as readily as a file path."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import httpx

from manhwatok.adapters.anilist import USER_AGENT
from manhwatok.domain.errors import ManhwatokError

MAX_BYTES = 25 * 1024 * 1024  # a slide is 1080x1920; anything larger is a mistake, not art
# What the renderer can open, by the type the server claims.
TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
SUFFIXES = set(TYPES.values()) | {".jpeg"}


def looks_like_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


def download_picture(
    url: str, into: Path, client: httpx.Client | None = None, timeout: float = 20.0
) -> Path:
    """Download `url` into `into` and return the file. Raises ManhwatokError on anything that
    isn't a picture the renderer can open — most often the gallery page rather than the image."""
    http = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        resp = http.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as e:
        raise ManhwatokError(f"could not download {url}: {e}") from e
    if resp.status_code >= 400:
        raise ManhwatokError(f"could not download {url}: HTTP {resp.status_code}")
    body = resp.content
    if not body:
        raise ManhwatokError(f"{url} came back empty")
    if len(body) > MAX_BYTES:
        raise ManhwatokError(f"{url} is too big ({len(body) // (1024 * 1024)} MB)")

    claimed = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    suffix = _suffix(url, claimed)
    if suffix is None:
        served = claimed or "nothing"
        raise ManhwatokError(
            f"{url} is not a picture — it served {served}. Link the image itself, not the "
            "page it sits on (right-click it and copy the image address)."
        )
    into.mkdir(parents=True, exist_ok=True)
    path = into / f"picture{suffix}"
    path.write_bytes(body)
    return path


def _suffix(url: str, content_type: str) -> str | None:
    """The extension to save under: what the URL says when that is usable, else what the server
    claims. None when neither names a picture the renderer can open."""
    if content_type and content_type not in TYPES:
        return None  # a real answer, and not one of ours (text/html, image/svg+xml, ...)
    from_url = PurePosixPath(urlparse(url).path).suffix.lower()
    if from_url in SUFFIXES:
        return ".jpg" if from_url == ".jpeg" else from_url
    return TYPES.get(content_type)
