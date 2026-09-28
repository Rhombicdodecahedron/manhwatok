from typing import NamedTuple, Protocol

from manhwatok.domain.models import CharacterPick, Manhwa, SearchQuery, TagInfo


class TitleExtras(NamedTuple):
    character_urls: list[str]  # pictured characters, most favourited first
    synonyms: list[str]  # AniList's alternative titles


class MetadataSource(Protocol):
    def search(self, query: SearchQuery) -> list[Manhwa]: ...

    def extras(self, ids: list[int]) -> dict[int, TitleExtras]:
        """What titles saved before these fields existed are missing, by AniList id."""
        ...

    def find(self, text: str, limit: int = 10) -> list[Manhwa]:
        """Titles matching free text, any country: the user named the one they meant."""
        ...

    def recommendations(self, anilist_id: int, limit: int = 25) -> list[Manhwa]:
        """What readers of the title recommend next, best rated first."""
        ...

    def characters(self, ids: list[int]) -> dict[int, list[CharacterPick]]:
        """Pictured characters by title id, in `Manhwa.characters` order."""
        ...

    def list_tags(self) -> list[TagInfo]: ...

    def list_genres(self) -> list[str]: ...


class ChapterSource(Protocol):
    def latest_chapter(self, manhwa: Manhwa) -> int | None: ...
