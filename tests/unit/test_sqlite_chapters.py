from datetime import datetime, timedelta, timezone

import pytest

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.domain.chapter import ChapterRecord, PartRecord
from manhwatok.domain.errors import StorageError

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=1)


@pytest.fixture
def chapters(tmp_path):
    with SqliteStore(tmp_path / "m.db") as store:
        yield store.chapters


def _record(number, anilist_id=1, **fields):
    return ChapterRecord(
        **{
            "anilist_id": anilist_id,
            "number": number,
            "chapter_id": f"id-{anilist_id}-{number}",
            "manhwa_title": "The Boxer",
            "pages": 36,
            **fields,
        }
    )


def _part(number, part=1, parts=1, post_id="20260920-a1c3", **fields):
    return PartRecord(
        **{
            "anilist_id": 1,
            "number": number,
            "language": "en",
            "part": part,
            "parts": parts,
            "post_id": post_id,
            "built_at": NOW,
            **fields,
        }
    )


def test_records_what_the_feed_listed_and_reads_it_back_in_number_order(chapters):
    chapters.record_chapters([_record("12"), _record("2"), _record("12.5")])
    assert [c.number for c in chapters.chapters(1)] == ["2", "12", "12.5"]
    assert chapters.chapters(1)[0].pages == 36


def test_re_recording_a_chapter_keeps_the_date_it_was_downloaded(chapters):
    """The feed says what exists; only this machine knows what it has fetched."""
    chapters.record_chapters([_record("12")])
    chapters.mark_downloaded(1, "12", "en", NOW)
    chapters.record_chapters([_record("12", pages=40, chapter_title="Talent")])
    [saved] = chapters.chapters(1)
    assert saved.downloaded_at == NOW
    assert (saved.pages, saved.chapter_title) == (40, "Talent")


def test_marking_a_chapter_downloaded_stamps_it_in_utc(chapters):
    chapters.record_chapters([_record("12")])
    chapters.mark_downloaded(1, "12", "en", NOW.astimezone(timezone(timedelta(hours=2))))
    assert chapters.chapters(1)[0].downloaded_at == NOW


def test_chapters_are_kept_apart_per_title_and_per_language(chapters):
    chapters.record_chapters([_record("1"), _record("1", anilist_id=2)])
    chapters.record_chapters([_record("1", language="es")])
    assert [c.anilist_id for c in chapters.chapters(1)] == [1]
    assert [c.language for c in chapters.chapters(1, "es")] == ["es"]


def test_parts_are_recorded_per_chapter_and_read_back_in_order(chapters):
    chapters.record_part(_part("12", part=2, parts=2, post_id="b"))
    chapters.record_part(_part("12", part=1, parts=2, post_id="a"))
    assert [(p.number, p.part, p.post_id) for p in chapters.parts(1)] == [
        ("12", 1, "a"),
        ("12", 2, "b"),
    ]


def test_rebuilding_a_part_replaces_the_post_that_carries_it(chapters):
    chapters.record_part(_part("12", post_id="old"))
    chapters.record_part(_part("12", post_id="new", built_at=LATER))
    [saved] = chapters.parts(1)
    assert (saved.post_id, saved.built_at) == ("new", LATER)


def test_publishing_a_post_stamps_every_part_it_carries(chapters):
    chapters.record_part(_part("12", part=1, parts=2, post_id="a"))
    chapters.record_part(_part("12", part=2, parts=2, post_id="b"))
    chapters.mark_published("a", NOW)
    published = {p.part: p.published_at for p in chapters.parts(1)}
    assert published == {1: NOW, 2: None}


def test_publishing_again_keeps_the_first_date(chapters):
    chapters.record_part(_part("12", post_id="a"))
    chapters.mark_published("a", LATER)
    chapters.mark_published("a", NOW)
    assert chapters.parts(1)[0].published_at == NOW


def test_forgetting_a_deleted_posts_parts_frees_them_to_be_built_again(chapters):
    chapters.record_part(_part("12", part=1, parts=2, post_id="a"))
    chapters.record_part(_part("12", part=2, parts=2, post_id="b"))
    chapters.forget_parts("a")
    assert [p.part for p in chapters.parts(1)] == [2]


def test_titles_lists_every_tracked_manhwa_alphabetically(chapters):
    chapters.record_chapters(
        [_record("1", anilist_id=2, manhwa_title="Your Throne"), _record("1")]
    )
    assert chapters.titles() == [(1, "The Boxer"), (2, "Your Throne")]


def test_nothing_tracked_yet_reads_back_empty(chapters):
    assert chapters.chapters(404) == [] and chapters.parts(404) == [] and chapters.titles() == []


def test_chapter_errors_after_close_are_storage_errors(tmp_path):
    store = SqliteStore(tmp_path / "m.db")
    store.close()
    with pytest.raises(StorageError):
        store.chapters.chapters(1)
