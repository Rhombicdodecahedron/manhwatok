from datetime import datetime

import pytest
from pydantic import ValidationError

from manhwatok.domain.caption import build_caption
from manhwatok.domain.models import ArtStyle
from manhwatok.domain.post import (
    DEFAULT_ACCENT,
    DEFAULT_CTA_FOLLOW,
    DEFAULT_CTA_TITLE,
    DEFAULT_HASHTAGS,
    ListPost,
    PostItem,
)
from tests.unit.fakes import manhwa, post


def test_slide_count_is_items_plus_cover_and_end():
    assert post().slide_count == 5


def test_post_without_items_is_unfinished():
    assert post(items=[]).is_unfinished
    assert not post().is_unfinished


def test_defaults():
    p = post()
    assert p.hashtags == DEFAULT_HASHTAGS
    assert p.accent == DEFAULT_ACCENT
    assert p.art is ArtStyle.NONE


def test_created_at_must_be_timezone_aware():
    with pytest.raises(ValidationError):
        post(created_at=datetime(2026, 9, 14, 12, 0))  # naive, no tzinfo


def test_json_round_trip():
    p = post()
    assert ListPost.model_validate_json(p.model_dump_json()) == p


def test_caption_lists_picks_and_hashtags_with_plain_title():
    assert build_caption(post(hashtags="#manhwa #webtoon")) == (
        "Manhwa where the MC regresses\n\n1. Title 1\n2. Title 2\n3. Title 3\n\n#manhwa #webtoon"
    )


# A post.json exactly as Phase 2 wrote it: no account, exported_at or CTA fields.
PHASE2_POST_JSON = """{
  "id": "20260914-8298",
  "created_at": "2026-09-14T20:11:05.123456Z",
  "title": "Manhwa where the MC *regresses*",
  "items": [
    {
      "manhwa": {
        "anilist_id": 136220,
        "title": "Doom Breaker",
        "romaji": "Pamyeol-ui Geomsa",
        "status": "HIATUS",
        "chapters": null,
        "latest_chapter": 101,
        "start_year": 2021,
        "genres": ["Action", "Fantasy"],
        "tags": ["Revenge"],
        "score": 78,
        "popularity": 21000,
        "cover_url": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/bx136220.jpg",
        "cover_color": "#43c9e4",
        "description": "Zephyr is the last human fighting evil.",
        "site_url": "https://anilist.co/manga/136220"
      },
      "hook": "Sent back ten years."
    }
  ],
  "candidates": [],
  "hashtags": "#manhwa",
  "accent": "#43c9e4"
}"""


def test_phase2_post_json_loads_with_new_defaults():
    p = ListPost.model_validate_json(PHASE2_POST_JSON)
    assert p.items[0].manhwa.title == "Doom Breaker"
    assert p.account is None
    assert p.exported_at is None
    assert p.cta_title == DEFAULT_CTA_TITLE == "Which one have you *read?*"
    assert p.cta_follow == DEFAULT_CTA_FOLLOW == "Follow for part 2"
    assert p.sent_at is None
    assert p.art is ArtStyle.NONE  # an older post keeps the look it was built with
    assert p.items[0].custom_art == ""  # no hand-picked art until you set one


def test_exported_at_must_be_timezone_aware():
    with pytest.raises(ValidationError):
        post(exported_at=datetime(2026, 9, 14, 12, 0))


def test_sent_at_must_be_timezone_aware():
    with pytest.raises(ValidationError):
        post(sent_at=datetime(2026, 9, 15, 12, 0))


def test_post_item_carries_hand_picked_art():
    item = PostItem(manhwa=manhwa(), hook="h", custom_art="art-11.png")
    assert item.custom_art == "art-11.png"
