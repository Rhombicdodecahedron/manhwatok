from datetime import datetime, timezone

import pytest

from manhwatok.app.kind_post import similar_candidates, similar_title
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError
from tests.unit.fakes import FakeHistory, FakeMetadata, manhwa

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


def test_similar_takes_the_seeds_recommendations_minus_blocked_and_recent():
    seed = manhwa(anilist_id=1, title="Seed")
    a, b, c = (
        manhwa(anilist_id=i, title=t, genres=g)
        for i, t, g in ((2, "A", ["Action"]), (3, "B", ["Romance"]), (4, "C", ["Action"]))
    )
    meta = FakeMetadata()
    meta.recommended[1] = [a, b, c]
    acct = Account(handle="reads", block_genres=["Romance"])
    found = similar_candidates(seed, acct, meta, None, FakeHistory(recent_ids=[4]), NOW)
    assert [m.title for m in found] == ["A"]


def test_similar_allows_repeats_when_asked():
    meta = FakeMetadata()
    meta.recommended[1] = [manhwa(anilist_id=4, title="C")]
    found = similar_candidates(
        manhwa(anilist_id=1), Account(handle="reads"), meta, None, FakeHistory([4]), NOW, True
    )
    assert [m.title for m in found] == ["C"]


def test_similar_without_recommendations_says_so():
    with pytest.raises(ManhwatokError, match="no recommendations for Seed"):
        similar_candidates(
            manhwa(anilist_id=1, title="Seed"), None, FakeMetadata(), None, FakeHistory(), NOW
        )


def test_similar_title_stars_the_seed():
    assert similar_title(manhwa(title="Omniscient Reader")) == "If you liked *Omniscient Reader*"


def test_a_similar_post_keeps_its_seed_and_kind():
    from manhwatok.app.build_post import create_post
    from manhwatok.domain.models import PostKind
    from manhwatok.domain.post import PostItem

    seed = manhwa(anilist_id=9, title="Seed")
    items = [PostItem(manhwa=manhwa(anilist_id=2))]
    p = create_post("x", NOW, [], "T", items, None, None, None, kind=PostKind.SIMILAR, seed=seed)
    assert p.kind is PostKind.SIMILAR and p.seed == seed
