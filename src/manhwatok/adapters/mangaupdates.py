"""MangaUpdates: latest released chapter for series AniList has no chapter count for."""

from __future__ import annotations

import re

import httpx

from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Manhwa

MU_API = "https://api.mangaupdates.com/v1"
USER_AGENT = "manhwatok/0.1"


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", s.casefold())


class MangaUpdatesSource:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    def latest_chapter(self, manhwa: Manhwa) -> int | None:
        for title in dict.fromkeys(t for t in (manhwa.title, manhwa.romaji) if t):
            series_id = self._find(title, manhwa.start_year)
            if series_id is not None:
                return self._latest(series_id)
        return None

    def _find(self, title: str, year: int | None) -> int | None:
        want = _norm(title)
        if not want:
            return None
        body = self._request("POST", "/series/search", json={"search": title, "perpage": 10})
        try:
            matches = [
                r["record"]
                for r in body.get("results", [])
                if r.get("record", {}).get("type") == "Manhwa"
                and want
                in (_norm(r.get("hit_title") or ""), _norm(r["record"].get("title") or ""))
            ]
            if not matches:
                return None
            if year is not None:
                for record in matches:
                    if record.get("year") == str(year):
                        return record["series_id"]
            return matches[0]["series_id"]
        except (KeyError, TypeError, AttributeError) as e:
            raise MetadataError(f"MangaUpdates response shape changed: {e}") from e

    def _latest(self, series_id: int) -> int | None:
        body = self._request("GET", f"/series/{series_id}")
        try:
            latest = body.get("latest_chapter")
        except AttributeError as e:
            raise MetadataError(f"MangaUpdates response shape changed: {e}") from e
        return latest if isinstance(latest, int) and latest > 0 else None

    def _request(self, method: str, path: str, **kwargs) -> dict:
        headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
        try:
            resp = self._client.request(method, MU_API + path, headers=headers, **kwargs)
        except httpx.HTTPError as e:
            raise MetadataError(f"MangaUpdates unreachable: {e}") from e
        if resp.status_code >= 400:
            raise MetadataError(f"MangaUpdates HTTP {resp.status_code} for {path}")
        try:
            return resp.json()
        except ValueError as e:
            raise MetadataError(f"MangaUpdates returned non-JSON for {path}") from e
