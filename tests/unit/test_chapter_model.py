from datetime import datetime, timezone

import pytest

from manhwatok.domain.chapter import (
    ChapterRecord,
    PartRecord,
    chapter_kicker,
    chapter_sort_key,
    missing_numbers,
    next_part,
    part_slices,
    starts_at,
)
from manhwatok.domain.post import MAX_ITEMS

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _chapter(number, **fields):
    return ChapterRecord(
        **{"anilist_id": 1, "number": number, "chapter_id": f"id-{number}", **fields}
    )


def _part(number, part, parts, **fields):
    return PartRecord(
        **{
            "anilist_id": 1,
            "number": number,
            "language": "en",
            "part": part,
            "parts": parts,
            "post_id": f"post-{number}-{part}",
            "built_at": NOW,
            **fields,
        }
    )


# --- chapter order ------------------------------------------------------------------------


def test_chapter_numbers_sort_by_value_not_by_text():
    numbers = ["100", "12", "2", "12.5"]
    assert sorted(numbers, key=chapter_sort_key) == ["2", "12", "12.5", "100"]


def test_unnumbered_chapters_sort_after_the_numbered_ones():
    """A oneshot has no chapter number; it belongs at the end, not at zero."""
    assert sorted(["", "3", "1"], key=chapter_sort_key) == ["1", "3", ""]


def test_a_number_that_is_not_a_number_still_sorts_somewhere():
    assert sorted(["4", "extra", "1"], key=chapter_sort_key) == ["1", "4", "extra"]


# --- what to build next -------------------------------------------------------------------


def test_next_part_is_the_first_chapter_when_nothing_was_built():
    found = next_part([_chapter("2"), _chapter("1")], [])
    assert (found.chapter.number, found.part, found.parts) == ("1", 1, 0)


def test_next_part_continues_the_chapter_whose_parts_are_unfinished():
    found = next_part([_chapter("1"), _chapter("2")], [_part("1", 1, 3)])
    assert (found.chapter.number, found.part, found.parts) == ("1", 2, 3)


def test_next_part_moves_to_the_next_chapter_once_every_part_is_built():
    parts = [_part("1", 1, 2), _part("1", 2, 2)]
    found = next_part([_chapter("1"), _chapter("2")], parts)
    assert (found.chapter.number, found.part) == ("2", 1)


def test_next_part_fills_a_gap_left_by_a_deleted_middle_part():
    parts = [_part("1", 1, 3), _part("1", 3, 3)]
    found = next_part([_chapter("1")], parts)
    assert (found.chapter.number, found.part, found.parts) == ("1", 2, 3)


def test_next_part_is_none_when_every_listed_chapter_is_built():
    parts = [_part("1", 1, 1), _part("2", 1, 1)]
    assert next_part([_chapter("1"), _chapter("2")], parts) is None


def test_next_part_of_nothing_is_none():
    assert next_part([], []) is None


def test_parts_of_another_chapter_do_not_count():
    assert next_part([_chapter("1")], [_part("9", 1, 1)]).part == 1


# --- splitting a chapter into posts --------------------------------------------------------


def test_part_slices_keep_a_short_chapter_in_one_post():
    assert part_slices(19) == [(0, 19)]


def test_part_slices_split_evenly_instead_of_leaving_a_one_slide_part():
    """34 panels are 17 and 17, not 33 and 1: a one-slide part is not worth posting."""
    assert part_slices(34) == [(0, 17), (17, 34)]


def test_part_slices_of_nothing_is_nothing():
    assert part_slices(0) == []


@pytest.mark.parametrize("total", [1, 2, 33, 34, 47, 66, 67, 100, 200])
def test_part_slices_never_exceed_the_slide_cap(total):
    assert all(end - start <= MAX_ITEMS for start, end in part_slices(total))


@pytest.mark.parametrize("total", [1, 2, 33, 34, 47, 66, 67, 100, 200])
def test_part_slices_cover_every_panel_exactly_once(total):
    covered = [panel for start, end in part_slices(total) for panel in range(start, end)]
    assert covered == list(range(total))


@pytest.mark.parametrize("total", [34, 47, 67, 100])
def test_part_slices_are_as_even_as_the_split_allows(total):
    sizes = [end - start for start, end in part_slices(total)]
    assert max(sizes) - min(sizes) <= 1


# --- what the cover says --------------------------------------------------------------------


def test_chapter_kicker_names_the_part_only_when_there_is_more_than_one():
    assert chapter_kicker("12", 1, 1) == "CHAPTER 12"
    assert chapter_kicker("12", 2, 3) == "CHAPTER 12 · PART 2/3"


def test_chapter_kicker_of_an_unnumbered_chapter_says_oneshot():
    assert chapter_kicker("", 1, 1) == "ONESHOT"


# --- what the source is missing ------------------------------------------------------------


def test_missing_numbers_finds_the_holes_inside_the_run():
    found = missing_numbers([_chapter("1"), _chapter("2"), _chapter("5"), _chapter("6")])
    assert found == ["3", "4"]


def test_missing_numbers_ignores_half_chapters_and_unnumbered_ones():
    assert missing_numbers([_chapter("1"), _chapter("1.5"), _chapter("2"), _chapter("")]) == []


def test_a_run_with_no_holes_is_missing_nothing():
    assert missing_numbers([_chapter("12"), _chapter("13")]) == []


def test_missing_numbers_of_nothing_is_nothing():
    assert missing_numbers([]) == []


def test_starts_at_is_the_first_numbered_chapter():
    assert starts_at([_chapter("13"), _chapter("12")]) == "12"
    assert starts_at([_chapter("")]) is None
    assert starts_at([]) is None


def test_a_run_that_starts_at_one_is_whole_from_the_beginning():
    assert starts_at([_chapter("1"), _chapter("2")]) == "1"
