from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from manhwatok.domain.account import Account
from manhwatok.domain.errors import InvalidName, ManhwatokError
from manhwatok.domain.plan import (
    RotationItem,
    clean_rotation,
    clean_slots,
    next_item,
    parse_slot,
    parse_when,
    upcoming_slots,
)

PARIS = ZoneInfo("Europe/Paris")


@pytest.mark.parametrize(
    ("raw", "kind", "value"),
    [
        ("chapter:Solo Leveling", "chapter", "Solo Leveling"),
        ("  Chapter :  151025 ", "chapter", "151025"),
        ("theme:isekai", "theme", "isekai"),
        ("THEME: Regression-Revenge", "theme", "regression-revenge"),
    ],
)
def test_rotation_items_parse_from_text(raw, kind, value):
    item = RotationItem.parse(raw)
    assert (item.kind, item.value) == (kind, value)
    assert str(item) == f"{kind}:{value}"


@pytest.mark.parametrize("raw", ["", "isekai", "list:isekai", ":isekai", "chapters:x"])
def test_anything_but_chapter_or_theme_is_refused(raw):
    with pytest.raises(ManhwatokError, match="chapter:<title> or theme:<name>"):
        RotationItem.parse(raw)


@pytest.mark.parametrize("raw", ["chapter:", "chapter:   ", "theme:"])
def test_an_item_names_something(raw):
    with pytest.raises(ManhwatokError, match="names nothing"):
        RotationItem.parse(raw)


def test_a_theme_item_takes_theme_name_rules():
    with pytest.raises(InvalidName, match="not a theme name"):
        RotationItem.parse("theme:no spaces allowed")


def test_clean_rotation_keeps_order_and_repeats_in_canonical_form():
    assert clean_rotation([" chapter: Solo Leveling", "Theme:Isekai", "chapter:Solo Leveling"]) == [
        "chapter:Solo Leveling",
        "theme:isekai",
        "chapter:Solo Leveling",
    ]


def test_next_item_takes_the_cursors_item_and_moves_on():
    rotation = ["chapter:a", "theme:b", "theme:c"]
    assert next_item(rotation, 0) == (RotationItem.parse("chapter:a"), 1)
    assert next_item(rotation, 1) == (RotationItem.parse("theme:b"), 2)


def test_next_item_wraps_around():
    rotation = ["chapter:a", "theme:b"]
    assert next_item(rotation, 1) == (RotationItem.parse("theme:b"), 0)


def test_a_cursor_past_a_shortened_rotation_wraps_too():
    assert next_item(["theme:b"], 5) == (RotationItem.parse("theme:b"), 0)
    assert next_item(["chapter:a", "theme:b"], 3) == (RotationItem.parse("theme:b"), 0)


def test_an_empty_rotation_has_no_next_item():
    with pytest.raises(ManhwatokError, match="no rotation"):
        next_item([], 0)


# --- slots -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "slot"),
    [
        ("mon 19:00", "mon 19:00"),
        ("  THU  9:05 ", "thu 09:05"),
        ("Daily 12:30", "daily 12:30"),
        ("sunday 0:00", "sun 00:00"),
        ("Wed 23:59", "wed 23:59"),
    ],
)
def test_slots_parse_to_one_spelling(raw, slot):
    assert parse_slot(raw) == slot


@pytest.mark.parametrize(
    "raw", ["", "mon", "19:00", "mon 24:00", "mon 19:60", "mon 19h", "moon 19:00", "mon 1900"]
)
def test_a_bad_slot_is_refused_with_the_form_to_use(raw):
    with pytest.raises(ManhwatokError, match=r"is not a slot — write <day> HH:MM"):
        parse_slot(raw)


def test_clean_slots_drops_repeats_and_keeps_order():
    assert clean_slots(["thu 19:00", "Mon 19:00", "thu 19:00 "]) == ["thu 19:00", "mon 19:00"]


def _account(*slots: str, tz: str = "Europe/Paris") -> Account:
    return Account(handle="reads", slots=list(slots), timezone=tz)


def test_upcoming_slots_are_the_weeks_times_in_the_accounts_zone_in_order():
    now = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)  # a Tuesday, 12:00 in Paris
    times = upcoming_slots(_account("thu 19:00", "mon 19:00"), now, 7)
    assert times == [
        datetime(2026, 9, 24, 19, 0, tzinfo=PARIS),
        datetime(2026, 9, 28, 19, 0, tzinfo=PARIS),
    ]
    assert all(t.tzinfo == PARIS for t in times)


def test_upcoming_slots_are_strictly_after_now_and_up_to_now_plus_days():
    now = datetime(2026, 9, 22, 19, 0, tzinfo=PARIS)  # Tuesday 19:00, a slot itself
    times = upcoming_slots(_account("tue 19:00"), now, 7)
    assert times == [datetime(2026, 9, 29, 19, 0, tzinfo=PARIS)]  # exactly now + 7 days is in
    assert upcoming_slots(_account("tue 19:00"), now, 6) == []


def test_a_daily_slot_comes_every_day_and_a_repeat_time_once():
    now = datetime(2026, 9, 22, 13, 0, tzinfo=PARIS)
    times = upcoming_slots(_account("daily 12:30", "wed 12:30"), now, 3)
    assert [t.day for t in times] == [23, 24, 25]


def test_slots_follow_the_accounts_own_zone():
    now = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    [t] = upcoming_slots(_account("wed 09:00", tz="Asia/Seoul"), now, 2)
    assert t == datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
    assert t.tzinfo == ZoneInfo("Asia/Seoul") and t.hour == 9


def test_no_slots_no_times():
    assert upcoming_slots(_account(), datetime(2026, 9, 22, tzinfo=timezone.utc), 7) == []


def test_a_slot_in_the_hour_skipped_in_march_moves_an_hour_on():
    # 29 March 2026: Paris goes from 02:00 CET straight to 03:00 CEST. 02:30 is read with the
    # offset before the change (fold=0), which is the instant 03:30 CEST.
    now = datetime(2026, 3, 28, 12, 0, tzinfo=PARIS)
    [t] = upcoming_slots(_account("sun 02:30"), now, 2)
    assert t == datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc)
    assert (t.hour, t.minute, t.utcoffset()) == (3, 30, timedelta(hours=2))


def test_a_slot_in_the_hour_repeated_in_october_is_its_first_pass():
    # 25 October 2026: Paris goes from 03:00 CEST back to 02:00 CET, so 02:30 happens twice.
    now = datetime(2026, 10, 24, 12, 0, tzinfo=PARIS)
    [t] = upcoming_slots(_account("sun 02:30"), now, 2)
    # (compared in UTC: Python never finds a time in a repeated hour equal to one in another zone)
    assert t.astimezone(timezone.utc) == datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    assert t.utcoffset() == timedelta(hours=2)


def test_a_week_across_a_change_keeps_the_wall_clock_time():
    now = datetime(2026, 10, 22, 12, 0, tzinfo=PARIS)
    times = upcoming_slots(_account("daily 19:00"), now, 7)
    assert {(t.hour, t.minute) for t in times} == {(19, 0)}
    assert len(times) == 7


# --- when a post goes out ---------------------------------------------------------------------

NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)  # Tuesday, 12:00 in Paris


def test_a_date_and_time_are_read_in_the_zone():
    assert parse_when("2026-09-24 19:00", "Europe/Paris", NOW) == datetime(
        2026, 9, 24, 17, 0, tzinfo=timezone.utc
    )
    assert parse_when(" 2026-09-24T9:30 ", "Asia/Seoul", NOW).hour == 9


def test_a_day_and_time_is_the_next_such_time():
    assert parse_when("thu 19:00", "Europe/Paris", NOW) == datetime(
        2026, 9, 24, 19, 0, tzinfo=PARIS
    )
    assert parse_when("tue 11:00", "Europe/Paris", NOW) == datetime(
        2026, 9, 29, 11, 0, tzinfo=PARIS
    )
    assert parse_when("daily 11:00", "Europe/Paris", NOW) == datetime(
        2026, 9, 23, 11, 0, tzinfo=PARIS
    )


def test_a_time_already_past_is_refused():
    with pytest.raises(ManhwatokError, match="already past"):
        parse_when("2026-09-22 11:59", "Europe/Paris", NOW)


@pytest.mark.parametrize("raw", ["", "tomorrow", "2026-09-24", "2026-13-01 10:00", "24/09 19:00"])
def test_anything_else_is_refused(raw):
    with pytest.raises(ManhwatokError, match="YYYY-MM-DD HH:MM"):
        parse_when(raw, "Europe/Paris", NOW)
