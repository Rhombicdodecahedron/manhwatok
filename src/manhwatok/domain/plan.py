"""An account's posting plan: the rotation of what its posts are about, taken in turn, and the
weekly slots its posts go out at."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.theme import normalize_theme_name

if TYPE_CHECKING:
    from manhwatok.domain.account import Account

CHAPTER = "chapter"  # the next part of a tracked title's chapters
THEME = "theme"  # a list post built from a saved theme

# What TikTok's own schedule takes: its calendar offers 10 days, its time picker 5-minute
# steps, and it won't schedule a post closer than a quarter of an hour away.
MAX_FILL_DAYS = 10
SCHEDULE_STEP_MINUTES = 5
MIN_SCHEDULE_MINUTES = 15


class RotationItem(BaseModel, frozen=True):
    """One step of a rotation. Written `chapter:<title>` (a title, or its AniList id, as
    `chapter build` takes it) or `theme:<name>` (a saved theme)."""

    kind: Literal["chapter", "theme"]
    value: str

    @classmethod
    def parse(cls, text: str) -> RotationItem:
        kind, colon, value = text.partition(":")
        kind, value = kind.strip().lower(), value.strip()
        if not colon or kind not in (CHAPTER, THEME):
            raise ManhwatokError(
                f"{text.strip()!r} is not a rotation item — write chapter:<title> or theme:<name>"
            )
        if not value:
            raise ManhwatokError(f"{text.strip()!r} names nothing — write {kind}:<something>")
        if kind == THEME:
            value = normalize_theme_name(value)
        return cls(kind=kind, value=value)

    def __str__(self) -> str:
        return f"{self.kind}:{self.value}"


def clean_rotation(items: list[str]) -> list[str]:
    """Each item checked and written the one way. Order and repeats are the plan's own: a
    rotation of chapter, theme, chapter posts that chapter twice as often."""
    return [str(RotationItem.parse(item)) for item in items]


def next_item(rotation: list[str], cursor: int) -> tuple[RotationItem, int]:
    """The item at `cursor` and where the cursor goes after it. Past the end it starts over,
    which also covers a cursor left beyond a rotation that has since been shortened."""
    if not rotation:
        raise ManhwatokError(
            "no rotation — set one with: manhwatok account set <handle> --rotation ..."
        )
    at = cursor % len(rotation)
    return RotationItem.parse(rotation[at]), (at + 1) % len(rotation)


# --- slots -----------------------------------------------------------------------------------

DAILY = "daily"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # date.weekday() order
_DAY_NAMES = {name: name for name in (*DAYS, DAILY)} | {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}
_SLOT = re.compile(r"([a-z]+)\s+(\d{1,2}):(\d{2})")
_DATE_TIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T]+(\d{1,2}):(\d{2})")


def _slot_parts(text: str) -> tuple[str, time] | None:
    found = _SLOT.fullmatch(text.strip().lower())
    if not found or found[1] not in _DAY_NAMES:
        return None
    hour, minute = int(found[2]), int(found[3])
    if hour > 23 or minute > 59:
        return None
    return _DAY_NAMES[found[1]], time(hour, minute)


def parse_slot(text: str) -> str:
    """A weekly posting time, written `<day> HH:MM` with day mon..sun (or its full name) or
    `daily`, in the account's time zone: "Mon 9:00" -> "mon 09:00"."""
    parts = _slot_parts(text)
    if parts is None:
        raise ManhwatokError(
            f"{text.strip()!r} is not a slot — write <day> HH:MM with day mon..sun or daily, "
            'e.g. "mon 19:00" or "daily 12:30"'
        )
    day, at = parts
    return f"{day} {at:%H:%M}"


def clean_slots(slots: list[str]) -> list[str]:
    """Each slot checked and written the one way, repeats dropped, in the order given."""
    return list(dict.fromkeys(parse_slot(slot) for slot in slots))


def local_time(day: date, at: time, zone: ZoneInfo) -> datetime:
    """`day` at wall-clock time `at` in `zone`, as the instant it names.

    A time a clock change leaves out (02:30 on the last Sunday of March in Paris) or passes
    twice (02:30 on the last Sunday of October) is read as zoneinfo reads it with fold=0, with
    the offset in force before the change: the missing 02:30 CET becomes 03:30 CEST, and the
    doubled 02:30 is its first pass, in CEST. The result is normalised, so its wall-clock time
    is one the zone's clocks actually show.

    Compare results as instants in UTC: Python never finds a time inside a repeated hour equal
    to a time in another zone, even the same instant (PEP 495)."""
    naive = datetime.combine(day, at, tzinfo=zone)  # fold=0
    return naive.astimezone(timezone.utc).astimezone(zone)


def upcoming_slots(account: Account, now: datetime, days: int) -> list[datetime]:
    """The instants the account's slots fall on after `now` (strictly) and up to `now + days`
    (24-hour days, however the clocks change), in order and in the account's time zone. Two
    slots that land on the same instant count once."""
    wanted = [p for p in (_slot_parts(s) for s in account.slots) if p is not None]
    return _slot_times(wanted, ZoneInfo(account.timezone), now, days)


def is_slot(account: Account, when: datetime) -> bool:
    """Whether `when` is one of the account's weekly slots: the instant a slot names on that
    day in the account's zone, read as `upcoming_slots` reads it across clock changes."""
    target = when.astimezone(timezone.utc)
    zone = ZoneInfo(account.timezone)
    day = target.astimezone(zone).date()
    for slot in account.slots:
        parts = _slot_parts(slot)
        if parts is None or parts[0] not in (DAILY, DAYS[day.weekday()]):
            continue
        if local_time(day, parts[1], zone).astimezone(timezone.utc) == target:
            return True
    return False


def _slot_times(
    wanted: list[tuple[str, time]], zone: ZoneInfo, now: datetime, days: int
) -> list[datetime]:
    start = now.astimezone(timezone.utc)
    end = start + timedelta(days=days)
    found: set[datetime] = set()
    day = start.astimezone(zone).date()
    while day <= end.astimezone(zone).date():
        for slot_day, at in wanted:
            if slot_day in (DAILY, DAYS[day.weekday()]):
                when = local_time(day, at, zone)
                if start < when <= end:
                    found.add(when.astimezone(timezone.utc))
        day += timedelta(days=1)
    return [when.astimezone(zone) for when in sorted(found)]


def parse_when(text: str, zone_name: str, now: datetime) -> datetime:
    """When one post goes out: `YYYY-MM-DD HH:MM` in the zone, or `<day> HH:MM` (a slot as
    `--slots` takes it) for the next such time. Refuses a time that isn't after `now`."""
    zone = ZoneInfo(zone_name)
    parts = _slot_parts(text)
    if parts is not None:
        return _slot_times([parts], zone, now, 8)[0]
    found = _DATE_TIME.fullmatch(text.strip())
    try:
        if found is None:
            raise ValueError
        year, month, dom, hour, minute = (int(g) for g in found.groups())
        when = local_time(date(year, month, dom), time(hour, minute), zone)
    except ValueError:
        raise ManhwatokError(
            f"{text.strip()!r} is not a time — write YYYY-MM-DD HH:MM or <day> HH:MM, "
            'e.g. "2026-09-24 19:00" or "thu 19:00"'
        ) from None
    if when <= now:
        raise ManhwatokError(f"{when:%Y-%m-%d %H:%M} ({zone_name}) is already past")
    return when


# --- TikTok's own schedule -------------------------------------------------------------------


def schedule_step(when: datetime) -> datetime:
    """`when` as TikTok's time picker can hold it: the minute rounded down to a multiple of 5
    (its list goes 00, 05, 10 … 55), seconds dropped. Rounding down never moves a post earlier
    than `check_schedule` allowed, since that checks the rounded time."""
    step = SCHEDULE_STEP_MINUTES
    return when.replace(minute=when.minute // step * step, second=0, microsecond=0)


def check_schedule(when: datetime, now: datetime) -> datetime:
    """`when` unchanged, once TikTok would take it as a scheduled time: the time the picker
    would really hold (see `schedule_step`) has to be at least 15 minutes and at most 10 days
    away. The uploader does the rounding itself, and says that it did."""
    at = schedule_step(when)
    minutes = (at - now).total_seconds() / 60
    local = at.astimezone()
    if minutes < MIN_SCHEDULE_MINUTES:
        raise ManhwatokError(
            f"{local:%Y-%m-%d %H:%M} is too soon — TikTok schedules a post at least "
            f"{MIN_SCHEDULE_MINUTES} minutes ahead (and on {SCHEDULE_STEP_MINUTES} minutes)"
        )
    if minutes > MAX_FILL_DAYS * 24 * 60:
        raise ManhwatokError(
            f"{local:%Y-%m-%d %H:%M} is too far off — TikTok schedules a post at most "
            f"{MAX_FILL_DAYS} days ahead"
        )
    return when


def schedulable(when: datetime | None, now: datetime) -> bool:
    """Whether TikTok would take `when` (see `check_schedule`); False for no time at all. What
    `upload` asks of a post's own slot before filling TikTok's schedule in with it."""
    if when is None:
        return False
    try:
        check_schedule(when, now)
    except ManhwatokError:
        return False
    return True
