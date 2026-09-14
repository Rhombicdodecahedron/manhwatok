import pytest

from manhwatok.app.suggest import suggest_titles
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import SearchQuery, Status
from tests.unit.fakes import FakeChapters, FakeMetadata, manhwa

Q = SearchQuery(tags=["Revenge"])


def test_passes_query_and_keeps_order_without_chapter_source():
    items = [manhwa(anilist_id=1, title="A"), manhwa(anilist_id=2, title="B")]
    meta = FakeMetadata(items)
    assert [m.title for m in suggest_titles(Q, meta)] == ["A", "B"]
    assert meta.queries == [Q]


def test_fills_only_missing_chapter_counts():
    finished = manhwa(anilist_id=1, status=Status.FINISHED, chapters=135)
    ongoing = manhwa(anilist_id=2, status=Status.RELEASING)
    chapters = FakeChapters({2: 212})
    out = suggest_titles(Q, FakeMetadata([finished, ongoing]), chapters)
    assert [m.chapter_count for m in out] == [135, 212]
    assert chapters.calls == [2]


def test_chapter_lookup_failure_reports_and_continues():
    msgs = []
    out = suggest_titles(
        Q,
        FakeMetadata([manhwa(title="Doom Breaker")]),
        FakeChapters(error=MetadataError("down")),
        progress=msgs.append,
    )
    assert out[0].latest_chapter is None
    assert msgs == ["no chapter count for Doom Breaker: down"]


def test_search_errors_propagate():
    class Down(FakeMetadata):
        def search(self, query):
            raise MetadataError("AniList unreachable")

    with pytest.raises(MetadataError):
        suggest_titles(Q, Down())
