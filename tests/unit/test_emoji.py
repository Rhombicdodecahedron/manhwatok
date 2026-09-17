"""Emojis derived from a post's picks: `auto` resolves to the genres its picks share."""

from manhwatok.domain.caption import build_caption, upload_title
from manhwatok.domain.emoji import AUTO, MAX_EMOJIS, emojis_for, post_emojis
from tests.unit.fakes import manhwa, post
from manhwatok.domain.post import PostItem


def picks(*genres: list[str]) -> list[PostItem]:
    return [
        PostItem(manhwa=manhwa(anilist_id=i, title=f"Title {i}", genres=list(g)))
        for i, g in enumerate(genres, 1)
    ]


def test_genre_in_more_than_half_the_picks_gives_its_emojis():
    assert emojis_for(picks(["Action"], ["Action"], ["Romance"])) == "🔥⚔️"


def test_genre_in_exactly_half_the_picks_is_not_a_majority():
    # Comedy is in 2 of 4 picks, Action in 3: only Action is a majority.
    assert emojis_for(picks(
        ["Action", "Comedy"], ["Action", "Comedy"], ["Action"], ["Romance"],
    )) == "🔥⚔️"


def test_majority_genres_come_in_pick_count_order():
    # Fantasy 3 picks, Action 4: Action's emojis first.
    assert emojis_for(picks(
        ["Action"], ["Action", "Fantasy"], ["Action", "Fantasy"], ["Action", "Fantasy"],
    )) == "🔥⚔️🐉✨"


def test_majority_genres_with_the_same_count_come_alphabetically():
    assert emojis_for(picks(["Fantasy", "Action"], ["Action", "Fantasy"])) == "🔥⚔️🐉✨"


def test_emojis_stop_at_the_cap():
    # Three majority genres, two emojis each: the third is dropped.
    shared = ["Action", "Fantasy", "Horror"]
    assert MAX_EMOJIS == 4
    assert emojis_for(picks(shared, shared)) == "🔥⚔️🐉✨"


def test_without_a_majority_the_commonest_genre_wins():
    assert emojis_for(picks(
        ["Action"], ["Action"], ["Fantasy"], ["Romance"], ["Horror"],
    )) == "🔥⚔️"


def test_without_a_majority_a_tie_is_broken_alphabetically():
    assert emojis_for(picks(["Romance"], ["Horror"])) == "🩸👁️"


def test_genres_the_table_does_not_know_are_ignored():
    assert emojis_for(picks(["Ecchi"], ["Ecchi"], ["Romance"])) == "💗🌹"


def test_picks_without_known_genres_give_no_emojis():
    assert emojis_for(picks(["Ecchi"], [])) == ""


def test_a_post_without_picks_gets_no_emojis():
    assert emojis_for([]) == ""


def test_post_emojis_resolves_auto_from_the_picks():
    p = post(items=picks(["Horror"], ["Horror"], ["Romance"]), emojis=AUTO)
    assert post_emojis(p) == "🩸👁️"


def test_post_emojis_keeps_emojis_the_user_chose():
    assert post_emojis(post(emojis="📚")) == "📚"
    assert post_emojis(post(emojis="")) == ""


def test_upload_title_appends_the_derived_emojis():
    p = post(items=picks(["Romance"], ["Romance"]), emojis=AUTO)
    assert upload_title(p) == "Manhwa where the MC regresses 💗🌹"


def test_caption_appends_the_derived_emojis():
    p = post(items=picks(["Romance"], ["Romance"]), emojis=AUTO, hashtags="#manhwa")
    assert build_caption(p).startswith("Manhwa where the MC regresses 💗🌹\n\n1. Title 1")


def test_an_auto_account_leaves_its_posts_on_auto():
    """A post keeps the marker, not the emojis of the picks it was built with: re-picking it
    changes the caption."""
    from datetime import datetime, timezone

    from manhwatok.app.build_post import create_post
    from manhwatok.domain.account import Account

    account = Account(handle="manhwa.generic", emojis=AUTO)
    items = picks(["Horror"], ["Horror"])
    built = create_post(
        "20260914-a3f9", datetime(2026, 9, 14, tzinfo=timezone.utc), [], "T", items, account,
        None, None,
    )
    assert built.emojis == AUTO
    assert post_emojis(built) == "🩸👁️"
    assert post_emojis(built.model_copy(update={"items": picks(["Romance"], ["Romance"])})) == "💗🌹"
