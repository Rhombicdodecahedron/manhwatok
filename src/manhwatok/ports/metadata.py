from typing import NamedTuple, Protocol

from manhwatok.domain.models import Manhwa, SearchQuery, TagInfo


class TitleExtras(NamedTuple):
    character_urls: list[str]  # pictured characters, most favourited first
    synonyms: list[str]  # AniList's alternative titles


class MetadataSource(Protocol):
    def search(self, query: SearchQuery) -> list[Manhwa]: ...

    def extras(self, ids: list[int]) -> dict[int, TitleExtras]:
        """What titles saved before these fields existed are missing, by AniList id."""
        ...

    def list_tags(self) -> list[TagInfo]: ...

    def list_genres(self) -> list[str]: ...


class ChapterSource(Protocol):
    def latest_chapter(self, manhwa: Manhwa) -> int | None: ...
