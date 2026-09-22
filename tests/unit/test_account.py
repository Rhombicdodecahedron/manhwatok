import pytest

from manhwatok.domain.account import DEFAULT_REPEAT_DAYS, Account, normalize_handle
from manhwatok.domain.errors import InvalidName, ManhwatokError
from manhwatok.domain.models import ArtStyle
from manhwatok.domain.post import (
    DEFAULT_ACCENT,
    DEFAULT_CTA_FOLLOW,
    DEFAULT_CTA_TITLE,
    DEFAULT_HASHTAGS,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@Manhwa.Daily", "manhwa.daily"),
        ("reads_24", "reads_24"),
        ("  @ab  ", "ab"),
        ("x" * 24, "x" * 24),
    ],
)
def test_normalize_handle(raw, expected):
    assert normalize_handle(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "@", "a", "@a", "x" * 25, "has space", "dash-ed", "@@ab", "é_ab"]
)
def test_bad_handles_raise_invalid_name(raw):
    with pytest.raises(InvalidName, match="not a TikTok handle"):
        normalize_handle(raw)


@pytest.mark.parametrize("raw", ["..", "._", "__", "...."])
def test_handles_need_a_letter_or_digit(raw):
    with pytest.raises(InvalidName, match="not a TikTok handle"):
        normalize_handle(raw)


def test_defaults():
    a = Account(handle="@Reads")
    assert a.handle == "reads"
    assert a.display == "@reads"
    assert (a.genres, a.block_genres, a.block_tags) == ([], [], [])
    assert a.hashtags == DEFAULT_HASHTAGS
    assert a.accent == DEFAULT_ACCENT
    assert a.cta_title == DEFAULT_CTA_TITLE
    assert a.cta_follow == DEFAULT_CTA_FOLLOW
    assert a.repeat_days == DEFAULT_REPEAT_DAYS == 30
    assert a.art is ArtStyle.NONE
    assert (a.emojis, a.sounds, a.default_sound) == ("", [], "")


def test_a_default_sound_is_tidied_like_the_others():
    a = Account(handle="ab", default_sound="  SOLO   LEVELING RaijinLofi ")
    assert a.default_sound == "SOLO LEVELING RaijinLofi"


def test_sounds_are_tidied_and_deduplicated_emojis_trimmed():
    sounds = ["  solo   leveling ", "", "solo leveling", "Dark Aria"]
    a = Account(handle="ab", sounds=sounds, emojis=" 🔥 ")
    assert a.sounds == ["solo leveling", "Dark Aria"]
    assert a.emojis == "🔥"


def test_accent_is_validated_and_lowercased():
    assert Account(handle="ab", accent="#43C9E4").accent == "#43c9e4"
    with pytest.raises(InvalidName, match="accent must look like #43c9e4"):
        Account(handle="ab", accent="cyan")


def test_name_lists_are_trimmed_and_deduplicated():
    a = Account(handle="ab", genres=[" Action", "Action", "", "Fantasy "])
    assert a.genres == ["Action", "Fantasy"]


@pytest.mark.parametrize("days", [0, 3651])
def test_repeat_days_bounds(days):
    with pytest.raises(ManhwatokError, match="repeat days must be 1–3650"):
        Account(handle="ab", repeat_days=days)


def test_cta_texts_cannot_be_blank():
    with pytest.raises(ManhwatokError, match="end-slide texts can't be empty"):
        Account(handle="ab", cta_follow="  ")


def test_json_round_trip():
    a = Account(handle="ab", genres=["Action"], block_tags=["Harem"], repeat_days=7)
    assert Account.model_validate_json(a.model_dump_json()) == a


def test_an_account_saved_with_a_song_note_still_loads():
    data = {"handle": "reads", "song": "Die For You"}  # the song note was dropped
    assert Account.model_validate(data) == Account(handle="reads")


def test_plan_fields_default_so_accounts_saved_before_them_load():
    old = Account.model_validate_json('{"handle": "reads"}')
    assert old.rotation == []
    assert old.rotation_cursor == 0
    assert old.timezone == "Europe/Paris"
    assert old.art_source is None
    assert old.slots == []


def test_rotation_items_are_checked_and_written_the_one_way():
    account = Account(handle="reads", rotation=["Chapter: Solo Leveling", "theme:Isekai"])
    assert account.rotation == ["chapter:Solo Leveling", "theme:isekai"]


def test_a_bad_rotation_item_is_refused():
    with pytest.raises(ManhwatokError, match="not a rotation item"):
        Account(handle="reads", rotation=["isekai"])


def test_the_rotation_cursor_is_never_negative():
    with pytest.raises(ManhwatokError, match="rotation cursor"):
        Account(handle="reads", rotation_cursor=-1)


def test_the_time_zone_is_an_iana_name():
    assert Account(handle="reads", timezone=" America/New_York ").timezone == "America/New_York"
    with pytest.raises(ManhwatokError, match="not a time zone"):
        Account(handle="reads", timezone="Mars/Olympus")
    with pytest.raises(ManhwatokError, match="not a time zone"):
        Account(handle="reads", timezone="")


def test_the_art_source_is_one_render_source_takes():
    from manhwatok.domain.models import ArtSourceName

    assert Account(handle="reads", art_source="pins").art_source is ArtSourceName.PINS
    with pytest.raises(ManhwatokError, match="covers, fanart, pins or reddit"):
        Account(handle="reads", art_source="instagram")


def test_slots_are_checked_and_written_the_one_way():
    account = Account(handle="reads", slots=["Mon 9:00", "daily 12:30", "mon 09:00"])
    assert account.slots == ["mon 09:00", "daily 12:30"]


def test_a_bad_slot_is_refused():
    with pytest.raises(ManhwatokError, match="is not a slot"):
        Account(handle="reads", slots=["monday at seven"])


def test_visibility_defaults_to_everyone_so_stored_accounts_load():
    from pydantic import ValidationError

    from manhwatok.domain.models import Visibility

    assert Account.model_validate_json('{"handle": "reads"}').visibility is Visibility.EVERYONE
    assert Account(handle="reads", visibility="friends").visibility is Visibility.FRIENDS
    with pytest.raises(ValidationError):
        Account(handle="reads", visibility="nobody")
