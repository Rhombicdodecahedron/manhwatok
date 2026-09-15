from datetime import datetime, timedelta, timezone

import pytest

from manhwatok.app.suggest import suggest_for_account, suggest_titles
from manhwatok.domain.account import Account
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import SearchQuery, Sort, Status
from tests.unit.fakes import FakeChapters, FakeHistory, FakeMetadata, manhwa

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
    assert msgs == [
        "looking up chapter counts for 1 title(s) on MangaUpdates…",
        "MangaUpdates unavailable, skipping chapter counts: down",
    ]


def test_chapter_lookup_failure_stops_further_lookups():
    ongoing = [
        manhwa(anilist_id=1, title="A"),
        manhwa(anilist_id=2, title="B"),
        manhwa(anilist_id=3, title="C"),
    ]
    chapters = FakeChapters(error=MetadataError("down"))
    out = suggest_titles(Q, FakeMetadata(ongoing), chapters)
    assert chapters.calls == [1]
    assert [m.latest_chapter for m in out] == [None, None, None]
    assert [m.title for m in out] == ["A", "B", "C"]


def test_no_progress_message_when_nothing_needs_a_lookup():
    finished = manhwa(anilist_id=1, status=Status.FINISHED, chapters=135)
    msgs = []
    out = suggest_titles(Q, FakeMetadata([finished]), FakeChapters({}), progress=msgs.append)
    assert msgs == []
    assert out[0].chapter_count == 135


def test_search_errors_propagate():
    class Down(FakeMetadata):
        def search(self, query):
            raise MetadataError("AniList unreachable")

    with pytest.raises(MetadataError):
        suggest_titles(Q, Down())


# --- per account ---------------------------------------------------------------------------

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


class ByGenre(FakeMetadata):
    """Answers each search with the list for the query's last genre (the allow-list genre)."""

    def __init__(self, lists: dict[str, list]):
        super().__init__()
        self.lists = lists

    def search(self, query: SearchQuery):
        self.queries.append(query)
        return list(self.lists.get(query.genres[-1] if query.genres else "", []))


def _m(anilist_id, score=None, popularity=0):
    return manhwa(
        anilist_id=anilist_id,
        title=f"T{anilist_id}",
        score=score,
        popularity=popularity,
        status=Status.FINISHED,
        chapters=10,
    )


def _suggest(meta, account, history=None, query=Q, allow_repeats=False, chapters=None, msgs=None):
    return suggest_for_account(
        query,
        account,
        meta,
        chapters,
        history if history is not None else FakeHistory(),
        now=NOW,
        allow_repeats=allow_repeats,
        progress=msgs.append if msgs is not None else lambda _: None,
    )


def test_without_account_it_is_the_phase1_search():
    meta = FakeMetadata([_m(1), _m(2)])
    history = FakeHistory({1})
    out = _suggest(meta, None, history)
    assert [m.anilist_id for m in out] == [1, 2]
    assert meta.queries == [Q]
    assert history.calls == []


def test_block_lists_become_exclusions():
    meta = FakeMetadata([_m(1)])
    query = SearchQuery(tags=["Revenge"], exclude_genres=["Horror"])
    account = Account(handle="ab", block_genres=["Romance", "Horror"], block_tags=["Harem"])
    _suggest(meta, account, query=query)
    [sent] = meta.queries
    assert sent.exclude_genres == ["Horror", "Romance"]
    assert sent.exclude_tags == ["Harem"]
    assert sent.tags == ["Revenge"]


def test_blocked_genres_and_tags_are_also_dropped_locally_ignoring_case():
    """Names saved while AniList was down stay as typed, and AniList may match them
    case-sensitively; a block must still hold."""
    meta = FakeMetadata(
        [
            _m(1).model_copy(update={"genres": ["Action", "Romance"]}),
            _m(2).model_copy(update={"tags": ["Revenge", "Harem"]}),
            _m(3).model_copy(update={"genres": ["Action"], "tags": ["Revenge"]}),
            _m(4),
        ]
    )
    account = Account(handle="ab", block_genres=["romance"], block_tags=["HAREM"])
    out = _suggest(meta, account, query=SearchQuery(tags=["x"], limit=2))
    assert [m.anilist_id for m in out] == [3, 4]


def test_allow_list_searches_each_genre_and_merges_by_score():
    meta = ByGenre(
        {
            "Action": [_m(1, score=70), _m(2, score=90), _m(3)],
            "Fantasy": [_m(2, score=90), _m(4, score=80)],
        }
    )
    account = Account(handle="ab", genres=["Action", "Fantasy"])
    out = _suggest(meta, account, query=SearchQuery(genres=["Drama"], limit=10))
    assert [q.genres for q in meta.queries] == [["Drama", "Action"], ["Drama", "Fantasy"]]
    assert [m.anilist_id for m in out] == [2, 4, 1, 3]  # deduped, score desc, unknown last


def test_allow_list_genre_already_in_the_query_is_not_repeated():
    meta = ByGenre({"Action": [_m(1)]})
    _suggest(meta, Account(handle="ab", genres=["Action"]), query=SearchQuery(genres=["Action"]))
    assert meta.queries[0].genres == ["Action"]


def test_allow_list_merge_by_popularity():
    meta = ByGenre(
        {"Action": [_m(1, popularity=5), _m(2, popularity=50)], "Fantasy": [_m(3, popularity=20)]}
    )
    account = Account(handle="ab", genres=["Action", "Fantasy"])
    out = _suggest(meta, account, query=SearchQuery(tags=["x"], sort=Sort.POPULARITY))
    assert [m.anilist_id for m in out] == [2, 3, 1]


def test_allow_list_trending_interleaves_round_robin():
    meta = ByGenre({"Action": [_m(1), _m(2), _m(3)], "Fantasy": [_m(4), _m(2), _m(5)]})
    account = Account(handle="ab", genres=["Action", "Fantasy"])
    out = _suggest(meta, account, query=SearchQuery(tags=["x"], sort=Sort.TRENDING))
    assert [m.anilist_id for m in out] == [1, 4, 2, 3, 5]


def test_recent_titles_are_over_fetched_then_dropped():
    meta = FakeMetadata([_m(i) for i in range(1, 8)])
    history = FakeHistory({2, 4})
    account = Account(handle="ab", repeat_days=7)
    out = _suggest(meta, account, history, query=SearchQuery(tags=["x"], limit=4))
    assert meta.queries[0].limit == 6
    assert [m.anilist_id for m in out] == [1, 3, 5, 6]
    assert history.calls == [("ab", NOW - timedelta(days=7))]


def test_over_fetch_is_capped_at_50():
    meta = FakeMetadata([_m(1)])
    _suggest(meta, Account(handle="ab"), FakeHistory(range(100, 140)), query=SearchQuery(limit=30))
    assert meta.queries[0].limit == 50


def test_allow_repeats_skips_history():
    meta = FakeMetadata([_m(1), _m(2)])
    history = FakeHistory({1})
    out = _suggest(meta, Account(handle="ab"), history, allow_repeats=True)
    assert [m.anilist_id for m in out] == [1, 2]
    assert history.calls == []
    assert meta.queries[0].limit == Q.limit


def test_skipped_repeats_are_reported():
    msgs = []
    _suggest(FakeMetadata([_m(1), _m(2)]), Account(handle="ab"), FakeHistory({1}), msgs=msgs)
    assert msgs == [
        "skipping 1 title(s) @ab exported in the last 30 days (--allow-repeats keeps them)"
    ]


def test_chapter_backfill_runs_only_on_the_kept_titles():
    ongoing = [manhwa(anilist_id=i, title=f"T{i}") for i in (1, 2, 3)]
    chapters = FakeChapters({3: 40})
    out = _suggest(
        FakeMetadata(ongoing),
        Account(handle="ab"),
        FakeHistory({1}),
        query=SearchQuery(tags=["x"], limit=1),
        chapters=chapters,
    )
    assert [m.anilist_id for m in out] == [2]
    assert chapters.calls == [2]
