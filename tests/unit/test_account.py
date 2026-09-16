import pytest

from manhwatok.domain.account import (
    DEFAULT_REPEAT_DAYS,
    Account,
    effective_song,
    normalize_handle,
)
from manhwatok.domain.errors import InvalidName, ManhwatokError
from manhwatok.domain.post import (
    DEFAULT_ACCENT,
    DEFAULT_CTA_FOLLOW,
    DEFAULT_CTA_TITLE,
    DEFAULT_HASHTAGS,
)
from tests.unit.fakes import post


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


def test_song_defaults_empty_and_is_trimmed():
    assert Account(handle="reads").song == ""
    assert Account(handle="reads", song="  Die For You ").song == "Die For You"


def test_account_json_without_a_song_loads():
    data = Account(handle="reads").model_dump(mode="json")
    del data["song"]
    assert Account.model_validate(data).song == ""


@pytest.mark.parametrize(
    "post_song, account, expected",
    [
        (None, Account(handle="reads", song="Acct Song"), "Acct Song"),
        ("Own Song", Account(handle="reads", song="Acct Song"), "Own Song"),
        ("", Account(handle="reads", song="Acct Song"), ""),
        (None, None, ""),
        ("Own Song", None, "Own Song"),
    ],
)
def test_effective_song(post_song, account, expected):
    assert effective_song(post(song=post_song), account) == expected
