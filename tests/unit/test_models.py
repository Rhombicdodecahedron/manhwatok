import pytest
from pydantic import ValidationError

from manhwatok.domain.models import Manhwa, SearchQuery, Sort, Status


def test_chapter_count_prefers_anilist_total():
    m = Manhwa(anilist_id=1, title="A", romaji="A", status=Status.FINISHED, chapters=135, latest_chapter=140)
    assert m.chapter_count == 135


def test_chapter_count_falls_back_to_latest_chapter():
    m = Manhwa(anilist_id=1, title="A", romaji="A", status=Status.RELEASING, latest_chapter=212)
    assert m.chapter_count == 212


def test_search_query_defaults():
    q = SearchQuery()
    assert (q.tags, q.genres, q.sort, q.limit, q.min_tag_rank) == ([], [], Sort.SCORE, 12, 60)


@pytest.mark.parametrize("limit", [0, 51])
def test_search_query_limit_bounds(limit):
    with pytest.raises(ValidationError):
        SearchQuery(limit=limit)
