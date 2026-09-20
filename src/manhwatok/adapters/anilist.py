"""AniList GraphQL: Korean manhwa search and the tag catalogue."""

from __future__ import annotations

import html
import re

import httpx

from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import QUAD_PICTURES, Manhwa, SearchQuery, Sort, Status, TagInfo
from manhwatok.ports.metadata import TitleExtras

ANILIST_URL = "https://graphql.anilist.co"
USER_AGENT = "manhwatok/0.1"

# tag_in / genre_in are AND filters; *_not_in drop titles with any of those; minimumTagRank
# drops weak tag matches.
_SEARCH = """
query ($perPage: Int, $genres: [String], $tags: [String], $sort: [MediaSort], $minTagRank: Int,
       $excludeGenres: [String], $excludeTags: [String]) {
  Page(page: 1, perPage: $perPage) {
    media(type: MANGA, countryOfOrigin: "KR", isAdult: false,
          genre_in: $genres, tag_in: $tags, sort: $sort, minimumTagRank: $minTagRank,
          genre_not_in: $excludeGenres, tag_not_in: $excludeTags) {
      id
      title { english romaji }
      status
      chapters
      startDate { year }
      genres
      tags { name rank isMediaSpoiler }
      averageScore
      popularity
      coverImage { extraLarge color }
      bannerImage
      characters(sort: FAVOURITES_DESC, perPage: 8) { nodes { image { large } } }
      synonyms
      description(asHtml: false)
      siteUrl
    }
  }
}
"""

_FIND = """
query ($text: String, $perPage: Int) {
  Page(page: 1, perPage: $perPage) {
    media(type: MANGA, search: $text, sort: [SEARCH_MATCH]) {
      id
      title { english romaji }
      status
      chapters
      startDate { year }
      genres
      tags { name rank isMediaSpoiler }
      averageScore
      popularity
      coverImage { extraLarge color }
      bannerImage
      characters(sort: FAVOURITES_DESC, perPage: 8) { nodes { image { large } } }
      synonyms
      description(asHtml: false)
      siteUrl
    }
  }
}
"""

_EXTRAS = """
query ($ids: [Int]) {
  Page(page: 1, perPage: 50) {
    media(id_in: $ids, type: MANGA) {
      id
      characters(sort: FAVOURITES_DESC, perPage: 8) { nodes { image { large } } }
      synonyms
    }
  }
}
"""

_TAGS = "{ MediaTagCollection { name category description isAdult } }"
_GENRES = "{ GenreCollection }"

_SORT = {
    Sort.SCORE: "SCORE_DESC",
    Sort.POPULARITY: "POPULARITY_DESC",
    Sort.TRENDING: "TRENDING_DESC",
}

_SOURCE_NOTE = re.compile(r"\(\s*source:[^)]*\)", re.IGNORECASE)


def _character_images(media: dict) -> list[str]:
    """Up to QUAD_PICTURES pictured characters AniList lists for a title, most favourited
    first. A listed character can have no picture at all, so those are skipped."""
    urls: list[str] = []
    for node in (media.get("characters") or {}).get("nodes") or []:
        url = ((node or {}).get("image") or {}).get("large") or ""
        if url and "default" not in url:  # AniList's stand-in for a character with no picture
            urls.append(url)
    return urls[:QUAD_PICTURES]


def clean_description(raw: str) -> str:
    """AniList 'plain' descriptions still carry <br>/<i> tags, entities and a (Source: X) note."""
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = _SOURCE_NOTE.sub("", html.unescape(text))
    lines = (" ".join(line.split()) for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


class AniListSource:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        """Close the HTTP client this source created (a client passed in stays open)."""
        if self._owns_client:
            self._client.close()

    def search(self, query: SearchQuery) -> list[Manhwa]:
        variables: dict = {
            "perPage": query.limit,
            "sort": [_SORT[query.sort]],
            "minTagRank": query.min_tag_rank,
        }
        if query.genres:
            variables["genres"] = query.genres
        if query.tags:
            variables["tags"] = query.tags
        if query.exclude_genres:
            variables["excludeGenres"] = query.exclude_genres
        if query.exclude_tags:
            variables["excludeTags"] = query.exclude_tags
        data = self._post(_SEARCH, variables)
        return [_to_manhwa(m) for m in data["Page"]["media"]]

    def find(self, text: str, limit: int = 10) -> list[Manhwa]:
        """Titles matching free text. Unlike `search` this does not filter to Korean comics:
        the user named this title, so the catalogue's best matches are what they meant."""
        if not text.strip():
            return []
        data = self._post(_FIND, {"text": text.strip(), "perPage": limit})
        return [_to_manhwa(m) for m in data["Page"]["media"]]

    def extras(self, ids: list[int]) -> dict[int, TitleExtras]:
        """Characters and alternative titles by AniList id, for titles saved before manhwatok
        kept them."""
        if not ids:
            return {}
        data = self._post(_EXTRAS, {"ids": list(ids)})
        return {
            m["id"]: TitleExtras(_character_images(m), [s for s in m.get("synonyms") or [] if s])
            for m in data["Page"]["media"]
        }

    def list_tags(self) -> list[TagInfo]:
        data = self._post(_TAGS, {})
        return [
            TagInfo(name=t["name"], category=t["category"], description=t.get("description") or "")
            for t in data["MediaTagCollection"]
            if not t["isAdult"]
        ]

    def list_genres(self) -> list[str]:
        return [g for g in self._post(_GENRES, {})["GenreCollection"] if g]

    def _post(self, query: str, variables: dict) -> dict:
        try:
            resp = self._client.post(
                ANILIST_URL,
                json={"query": query, "variables": variables},
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            )
        except httpx.HTTPError as e:
            raise MetadataError(f"AniList unreachable: {e}") from e
        if resp.status_code == 429:
            raise MetadataError(
                f"AniList rate limit hit — retry in {resp.headers.get('Retry-After', '60')}s"
            )
        try:
            body = resp.json()
        except ValueError as e:
            raise MetadataError(f"AniList returned non-JSON (HTTP {resp.status_code})") from e
        if body.get("errors"):
            raise MetadataError(
                "AniList: " + "; ".join(err.get("message", "?") for err in body["errors"])
            )
        if resp.status_code >= 400 or not body.get("data"):
            raise MetadataError(f"AniList HTTP {resp.status_code}")
        return body["data"]


def _to_manhwa(m: dict) -> Manhwa:
    title = m.get("title") or {}
    romaji = title.get("romaji") or ""
    try:
        status = Status(m.get("status"))
    except ValueError:
        status = Status.UNKNOWN
    return Manhwa(
        anilist_id=m["id"],
        title=title.get("english") or romaji,
        romaji=romaji,
        status=status,
        chapters=m.get("chapters"),
        start_year=(m.get("startDate") or {}).get("year"),
        genres=m.get("genres") or [],
        tags=[t["name"] for t in m.get("tags") or [] if not t.get("isMediaSpoiler")],
        score=m.get("averageScore"),
        popularity=m.get("popularity") or 0,
        cover_url=(m.get("coverImage") or {}).get("extraLarge") or "",
        cover_color=(m.get("coverImage") or {}).get("color"),
        banner_url=m.get("bannerImage") or "",
        character_url=next(iter(_character_images(m)), ""),
        character_urls=_character_images(m),
        synonyms=[s for s in m.get("synonyms") or [] if s],
        description=clean_description(m.get("description") or ""),
        site_url=m.get("siteUrl") or "",
    )
