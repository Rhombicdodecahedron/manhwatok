from typing import Protocol

from manhwatok.domain.models import Manhwa, SearchQuery, TagInfo


class MetadataSource(Protocol):
    def search(self, query: SearchQuery) -> list[Manhwa]: ...

    def list_tags(self) -> list[TagInfo]: ...


class ChapterSource(Protocol):
    def latest_chapter(self, manhwa: Manhwa) -> int | None: ...
