from manhwatok.domain.caption import build_caption
from manhwatok.domain.post import DEFAULT_ACCENT, DEFAULT_HASHTAGS, ListPost
from tests.unit.fakes import post


def test_slide_count_is_items_plus_cover_and_end():
    assert post().slide_count == 5


def test_post_without_items_is_unfinished():
    assert post(items=[]).is_unfinished
    assert not post().is_unfinished


def test_defaults():
    p = post()
    assert p.hashtags == DEFAULT_HASHTAGS
    assert p.accent == DEFAULT_ACCENT


def test_json_round_trip():
    p = post()
    assert ListPost.model_validate_json(p.model_dump_json()) == p


def test_caption_lists_picks_and_hashtags_with_plain_title():
    assert build_caption(post(hashtags="#manhwa #webtoon")) == (
        "Manhwa where the MC regresses\n\n1. Title 1\n2. Title 2\n3. Title 3\n\n#manhwa #webtoon"
    )
