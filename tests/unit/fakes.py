from datetime import datetime, timezone

from manhwatok.domain.models import Manhwa, SearchQuery, Status, TagInfo
from manhwatok.domain.post import ListPost, PostItem


def manhwa(**overrides) -> Manhwa:
    fields = {"anilist_id": 1, "title": "Test Manhwa", "romaji": "Teseuteu", "status": Status.RELEASING}
    fields.update(overrides)
    return Manhwa(**fields)


class FakeMetadata:
    def __init__(self, results=(), tags=()):
        self.results: list[Manhwa] = list(results)
        self.tags: list[TagInfo] = list(tags)
        self.queries: list[SearchQuery] = []

    def search(self, query: SearchQuery) -> list[Manhwa]:
        self.queries.append(query)
        return list(self.results)

    def list_tags(self) -> list[TagInfo]:
        return list(self.tags)


class FakeChapters:
    def __init__(self, latest: dict[int, int | None] | None = None, error: Exception | None = None):
        self.latest = dict(latest or {})
        self.error = error
        self.calls: list[int] = []

    def latest_chapter(self, manhwa: Manhwa) -> int | None:
        self.calls.append(manhwa.anilist_id)
        if self.error:
            raise self.error
        return self.latest.get(manhwa.anilist_id)


def post(**overrides) -> ListPost:
    items = overrides.pop("items", None)
    if items is None:
        items = [
            PostItem(manhwa=manhwa(anilist_id=i, title=f"Title {i}"), hook=f"Hook {i}")
            for i in (1, 2, 3)
        ]
    fields = {
        "id": "20260914-a3f9",
        "created_at": datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
        "title": "Manhwa where the MC *regresses*",
        "items": items,
        "candidates": [item.manhwa for item in items],
    }
    fields.update(overrides)
    return ListPost(**fields)
