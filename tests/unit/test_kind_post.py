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


def _cast(meta):
    from manhwatok.domain.models import CharacterPick

    meta.cast[1] = [
        CharacterPick(name="Jin", role="MAIN", index=0, image_url="https://x/jin.png"),
        CharacterPick(name="Hae", role="SUPPORTING", index=1, image_url="https://x/hae.png"),
    ]


def test_characters_take_the_chosen_one_and_refresh_the_pictures():
    from manhwatok.app.kind_post import with_characters
    from manhwatok.domain.post import PostItem

    meta = FakeMetadata()
    _cast(meta)
    (item,) = with_characters([PostItem(manhwa=manhwa(anilist_id=1, title="T1"))], meta, {1: 1})
    assert item.character.name == "Hae"
    assert item.manhwa.character_urls == ["https://x/jin.png", "https://x/hae.png"]
    assert item.hook == "Supporting · T1"


def test_characters_default_to_the_most_favourited_and_keep_a_written_hook():
    from manhwatok.app.kind_post import with_characters
    from manhwatok.domain.post import PostItem

    meta = FakeMetadata()
    _cast(meta)
    (item,) = with_characters([PostItem(manhwa=manhwa(anilist_id=1), hook="Mine")], meta)
    assert item.character.name == "Jin" and item.hook == "Mine"


def test_a_title_without_characters_is_refused_by_name():
    from manhwatok.app.kind_post import with_characters
    from manhwatok.domain.post import PostItem

    with pytest.raises(ManhwatokError, match="T9 has no pictured characters"):
        with_characters([PostItem(manhwa=manhwa(anilist_id=9, title="T9"))], FakeMetadata())
