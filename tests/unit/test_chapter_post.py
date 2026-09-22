from datetime import datetime, timezone

import pytest

from manhwatok.app.chapter_post import (
    chosen_part,
    build_chapter_post,
    chapter_status,
    next_to_build,
    refresh_chapters,
    resolve_title,
    tracked_title,
)
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError, MetadataError
from manhwatok.ports.chapters import ChapterInfo
from tests.unit.fakes import (
    FakeChapterPages,
    FakeCutter,
    FakeMetadata,
    make_chapter_tools,
    make_tools,
    manhwa,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
BOXER = manhwa(anilist_id=119174, title="The Boxer")
CH12 = ChapterInfo("ch-12", "12", "Talent", "en", 36)
CH13 = ChapterInfo("ch-13", "13", "", "en", 37)


def _tools(tmp_path, **fields):
    return make_tools(tmp_path, **fields)


def _chapter_tools(tmp_path, chapters=(CH12, CH13), panels=4, **fields):
    pages = fields.pop("pages", None) or FakeChapterPages(chapters=list(chapters))
    return make_chapter_tools(tmp_path, pages=pages, cutter=FakeCutter(panels), **fields)


def _build(tmp_path, ct, tools=None, account=None, **fields):
    return build_chapter_post(BOXER, tools or _tools(tmp_path), ct, account, NOW, **fields)


# --- building -----------------------------------------------------------------------------------


def test_builds_the_first_part_of_the_first_chapter_of_a_fresh_title(tmp_path):
    ct = _chapter_tools(tmp_path)
    post, slides = _build(tmp_path, ct)
    assert post.chapter.number == "12" and post.chapter.part == 1
    assert len(slides) == post.slide_count
    assert post.title == "The Boxer *Chapter 12*"


def test_the_next_build_continues_where_the_last_post_stopped(tmp_path):
    ct = _chapter_tools(tmp_path, panels=40)  # two parts
    tools = _tools(tmp_path)
    first, _ = _build(tmp_path, ct, tools)
    second, _ = _build(tmp_path, ct, tools)
    third, _ = _build(tmp_path, ct, tools)
    assert [(p.chapter.number, p.chapter.part) for p in (first, second, third)] == [
        ("12", 1),
        ("12", 2),
        ("13", 1),
    ]


def test_a_chapter_longer_than_the_cap_is_split_across_several_posts(tmp_path):
    ct = _chapter_tools(tmp_path, panels=40)
    post, _ = _build(tmp_path, ct)
    assert (post.chapter.parts, len(post.chapter.panels)) == (2, 20)
    assert (post.chapter.from_panel, post.chapter.to_panel) == (0, 20)


def test_an_explicit_chapter_number_beats_continuing(tmp_path):
    ct = _chapter_tools(tmp_path)
    post, _ = _build(tmp_path, ct, number="13")
    assert post.chapter.number == "13"


def test_an_unknown_chapter_number_fails_naming_what_is_listed(tmp_path):
    ct = _chapter_tools(tmp_path)
    with pytest.raises(ManhwatokError, match="12, 13"):
        _build(tmp_path, ct, number="99")


def test_a_part_past_the_last_one_fails_naming_how_many_there_are(tmp_path):
    ct = _chapter_tools(tmp_path)
    with pytest.raises(ManhwatokError, match="1 part"):
        _build(tmp_path, ct, part=4)


def test_a_title_without_english_chapters_is_skipped_with_a_clear_message(tmp_path):
    ct = _chapter_tools(tmp_path, chapters=())
    with pytest.raises(ManhwatokError, match="no English chapters"):
        _build(tmp_path, ct)


def test_a_source_failure_is_reported_as_it_came(tmp_path):
    pages = FakeChapterPages(error=MetadataError("MangaDex is down"))
    ct = _chapter_tools(tmp_path, pages=pages)
    with pytest.raises(MetadataError, match="MangaDex is down"):
        _build(tmp_path, ct)


def test_every_listed_chapter_built_says_so_instead_of_building_nothing(tmp_path):
    ct = _chapter_tools(tmp_path, chapters=(CH12,))
    tools = _tools(tmp_path)
    _build(tmp_path, ct, tools)
    with pytest.raises(ManhwatokError, match="already built"):
        _build(tmp_path, ct, tools)


def test_the_panels_of_this_part_are_copied_into_the_posts_own_folder(tmp_path):
    ct = _chapter_tools(tmp_path, panels=40)
    tools = _tools(tmp_path)
    post, _ = _build(tmp_path, ct, tools)
    folder = tools.posts.folder(post.id)
    assert [p.name for p in sorted(folder.glob("panel-*.png"))] == post.chapter.panels
    assert len(post.chapter.panels) == 20


def test_the_post_carries_the_chapter_the_part_and_the_panel_range(tmp_path):
    ct = _chapter_tools(tmp_path, panels=40)
    tools = _tools(tmp_path)
    _build(tmp_path, ct, tools)
    second, _ = _build(tmp_path, ct, tools)
    part = second.chapter
    assert (part.chapter_id, part.pages, part.language) == ("ch-12", 36, "en")
    assert (part.part, part.parts, part.from_panel, part.to_panel) == (2, 2, 20, 40)


def test_the_post_takes_the_accounts_style(tmp_path):
    account = Account(handle="reads", hashtags="#chapters", accent="#ff5a5f", emojis="🥊")
    post, _ = _build(tmp_path, _chapter_tools(tmp_path), account=account)
    assert (post.account, post.hashtags, post.accent, post.emojis) == (
        "reads",
        "#chapters",
        "#ff5a5f",
        "🥊",
    )


def test_the_post_without_an_account_falls_back_to_the_defaults(tmp_path):
    from manhwatok.domain.post import DEFAULT_ACCENT, DEFAULT_HASHTAGS

    post, _ = _build(tmp_path, _chapter_tools(tmp_path))
    assert (post.account, post.hashtags, post.accent) == (None, DEFAULT_HASHTAGS, DEFAULT_ACCENT)


def test_the_part_is_recorded_once_the_post_is_saved(tmp_path):
    ct = _chapter_tools(tmp_path)
    post, _ = _build(tmp_path, ct)
    [record] = ct.chapters.parts(119174)
    assert (record.number, record.part, record.post_id) == ("12", 1, post.id)
    assert record.built_at == NOW and record.published_at is None


def test_downloading_a_chapter_marks_it_downloaded(tmp_path):
    ct = _chapter_tools(tmp_path)
    _build(tmp_path, ct)
    downloaded = {c.number: c.downloaded_at for c in ct.chapters.chapters(119174)}
    assert downloaded["12"] == NOW and downloaded["13"] is None


def test_pages_already_cut_are_not_cut_again(tmp_path):
    ct = _chapter_tools(tmp_path, panels=40)
    tools = _tools(tmp_path)
    _build(tmp_path, ct, tools)
    _build(tmp_path, ct, tools)  # part 2 of the same chapter
    assert len(ct.cutter.cuts) == 1


# --- listing ---------------------------------------------------------------------------------


def test_refresh_records_the_feed_and_returns_it_in_chapter_order(tmp_path):
    ct = _chapter_tools(tmp_path, chapters=(CH13, CH12))
    found = refresh_chapters(BOXER, ct, NOW)
    assert [c.number for c in found] == ["12", "13"]
    assert [c.number for c in ct.chapters.chapters(119174)] == ["12", "13"]
    assert found[0].manhwa_title == "The Boxer"


def test_refresh_keeps_the_download_dates_of_chapters_it_already_knew(tmp_path):
    ct = _chapter_tools(tmp_path)
    _build(tmp_path, ct)
    refresh_chapters(BOXER, ct, NOW)
    assert ct.chapters.chapters(119174)[0].downloaded_at == NOW


def test_refresh_of_a_title_without_english_chapters_says_so(tmp_path):
    ct = _chapter_tools(tmp_path, chapters=())
    with pytest.raises(ManhwatokError, match="no English chapters"):
        refresh_chapters(BOXER, ct, NOW)


def test_chapter_status_reports_listed_built_and_published(tmp_path):
    ct = _chapter_tools(tmp_path, panels=40)
    tools = _tools(tmp_path)
    post, _ = _build(tmp_path, ct, tools)
    ct.chapters.mark_published(post.id, NOW)
    status = {s.chapter.number: s for s in chapter_status(119174, ct)}
    assert (status["12"].built, status["12"].published) == (1, 1)
    assert status["12"].chapter.downloaded_at == NOW
    assert (status["13"].built, status["13"].published) == (0, 0)


def test_next_to_build_lists_a_title_nothing_is_on_record_for(tmp_path):
    ct = _chapter_tools(tmp_path)
    progress = []
    found = next_to_build(BOXER, ct, NOW, progress=progress.append)
    assert (found.chapter.number, found.part, found.parts) == ("12", 1, 0)
    assert ct.pages.listings == [119174]
    assert progress == ["The Boxer: 2 chapters listed"]


def test_next_to_build_uses_the_record_while_a_part_is_left(tmp_path):
    ct = _chapter_tools(tmp_path, panels=40)
    _build(tmp_path, ct)
    ct.pages.listings.clear()
    found = next_to_build(BOXER, ct, NOW)
    assert (found.chapter.number, found.part, found.parts) == ("12", 2, 2)
    assert ct.pages.listings == []


def test_next_to_build_asks_the_source_again_once_everything_on_record_is_built(tmp_path):
    ct = _chapter_tools(tmp_path, chapters=(CH12,))
    _build(tmp_path, ct)
    assert next_to_build(BOXER, ct, NOW) is None
    ct.pages.listed.append(CH13)
    found = next_to_build(BOXER, ct, NOW)
    assert (found.chapter.number, found.part) == ("13", 1)


def test_next_to_build_in_another_language(tmp_path):
    fr = ChapterInfo("fr-1", "1", "", "fr", 20)
    ct = _chapter_tools(tmp_path, chapters=(CH12, fr))
    assert next_to_build(BOXER, ct, NOW, "fr").chapter.chapter_id == "fr-1"


# --- naming a title ------------------------------------------------------------------------------


def test_resolve_title_accepts_an_anilist_id_as_well_as_a_search(tmp_path):
    from tests.unit.test_mangadex import MemoryCache

    meta = FakeMetadata([BOXER])
    cache = MemoryCache()
    assert resolve_title("The Boxer", meta, cache).anilist_id == 119174
    assert resolve_title("119174", meta, cache).title == "The Boxer"


def test_resolve_title_reuses_the_cached_title_instead_of_searching_again(tmp_path):
    from tests.unit.test_mangadex import MemoryCache

    meta = FakeMetadata([BOXER])
    cache = MemoryCache()
    resolve_title("The Boxer", meta, cache)
    resolve_title("119174", meta, cache)
    assert meta.searches == ["The Boxer"]


def test_a_tracked_title_comes_from_the_cache_by_id(tmp_path):
    from tests.unit.test_mangadex import MemoryCache

    meta = FakeMetadata([BOXER])
    cache = MemoryCache()
    cache.put("manhwa:119174", BOXER.model_dump_json())
    assert tracked_title(119174, "The Boxer", meta, cache) == BOXER
    assert meta.searches == []


def test_a_tracked_title_not_in_the_cache_is_searched_by_its_name(tmp_path):
    from tests.unit.test_mangadex import MemoryCache

    meta = FakeMetadata([BOXER])
    assert tracked_title(119174, "The Boxer", meta, MemoryCache()) == BOXER
    assert meta.searches == ["The Boxer"]


def test_resolve_title_that_matches_nothing_says_so(tmp_path):
    from tests.unit.test_mangadex import MemoryCache

    with pytest.raises(ManhwatokError, match="nothing called"):
        resolve_title("no such thing", FakeMetadata([BOXER]), MemoryCache())


def test_resolve_title_lists_the_near_matches_when_several_fit(tmp_path):
    from tests.unit.test_mangadex import MemoryCache

    other = manhwa(anilist_id=2, title="The Boxer's Son")
    with pytest.raises(ManhwatokError, match="The Boxer's Son"):
        resolve_title("boxer", FakeMetadata([BOXER, other]), MemoryCache())


def test_the_end_slide_of_a_middle_part_points_at_the_next_one(tmp_path):
    ct = _chapter_tools(tmp_path, panels=40)
    post, _ = _build(tmp_path, ct)
    assert post.cta_title == "Part *2* next"


def test_the_end_slide_of_the_last_part_closes_the_chapter(tmp_path):
    ct = _chapter_tools(tmp_path)
    post, _ = _build(tmp_path, ct)
    assert post.cta_title == "Chapter *12* done"


def test_an_account_that_wrote_its_own_end_slide_title_keeps_it(tmp_path):
    account = Account(handle="reads", cta_title="Read it on *Webtoon*")
    post, _ = _build(tmp_path, _chapter_tools(tmp_path), account=account)
    assert post.cta_title == "Read it on *Webtoon*"


# --- what is missing ---------------------------------------------------------------------------


def _records(numbers):
    from manhwatok.domain.chapter import ChapterRecord

    return [
        ChapterRecord(anilist_id=119174, number=n, chapter_id=f"id-{n}", manhwa_title="The Boxer")
        for n in numbers
    ]


def test_a_run_that_starts_late_says_so_and_where_the_rest_is(tmp_path):
    from manhwatok.app.chapter_post import missing_report

    pages = FakeChapterPages(elsewhere={"es": 11, "it": 9})
    ct = _chapter_tools(tmp_path, pages=pages)
    lines = missing_report(BOXER, ct, _records(["12", "13"]))
    assert "English starts at chapter 12" in lines[0]
    assert "chapters 1–11" in lines[1] and "Spanish (11)" in lines[1] and "Italian (9)" in lines[1]


def test_a_run_that_starts_at_one_says_nothing(tmp_path):
    from manhwatok.app.chapter_post import missing_report

    ct = _chapter_tools(tmp_path)
    assert missing_report(BOXER, ct, _records(["1", "2", "3"])) == []


def test_holes_inside_the_run_are_named(tmp_path):
    from manhwatok.app.chapter_post import missing_report

    ct = _chapter_tools(tmp_path)
    [line] = missing_report(BOXER, ct, _records(["1", "2", "5"]))
    assert "missing from the English run: 3, 4" == line


def test_a_late_start_with_nothing_elsewhere_says_only_the_start(tmp_path):
    from manhwatok.app.chapter_post import missing_report

    ct = _chapter_tools(tmp_path, pages=FakeChapterPages(elsewhere={}))
    [line] = missing_report(BOXER, ct, _records(["12"]))
    assert "starts at chapter 12" in line


# --- choosing a source --------------------------------------------------------------------------


def _both(tmp_path, mangadex=(CH12,), webtoons=(), **fields):
    from manhwatok.domain.models import ChapterSourceName

    other = FakeChapterPages(chapters=list(webtoons))
    other.root = tmp_path
    return make_chapter_tools(
        tmp_path,
        pages=FakeChapterPages(chapters=list(mangadex), **fields),
        sources={ChapterSourceName.WEBTOONS: other},
    )


def test_the_first_source_with_the_title_is_the_one_used(tmp_path):
    from manhwatok.app.chapter_post import pick_source
    from manhwatok.domain.models import ChapterSourceName

    ct = _both(tmp_path, mangadex=(), webtoons=(CH12,))
    assert pick_source(BOXER, ct).source is ChapterSourceName.WEBTOONS


def test_mangadex_is_tried_first(tmp_path):
    from manhwatok.app.chapter_post import pick_source
    from manhwatok.domain.models import ChapterSourceName

    ct = _both(tmp_path, mangadex=(CH12,), webtoons=(CH13,))
    assert pick_source(BOXER, ct).source is ChapterSourceName.MANGADEX


def test_a_source_asked_for_by_name_is_used_whatever_the_others_have(tmp_path):
    from manhwatok.app.chapter_post import pick_source
    from manhwatok.domain.models import ChapterSourceName

    ct = _both(tmp_path, mangadex=(CH12,), webtoons=())
    picked = pick_source(BOXER, ct, wanted=ChapterSourceName.WEBTOONS)
    assert picked.source is ChapterSourceName.WEBTOONS


def test_a_title_keeps_the_source_it_is_already_tracked_under(tmp_path):
    from manhwatok.app.chapter_post import pick_source, refresh_chapters
    from manhwatok.domain.models import ChapterSourceName

    ct = _both(tmp_path, mangadex=(CH12,), webtoons=(CH12, CH13))
    refresh_chapters(BOXER, ct.using(ChapterSourceName.WEBTOONS), NOW)
    assert pick_source(BOXER, ct).source is ChapterSourceName.WEBTOONS


def test_a_source_that_fails_does_not_stop_the_next_being_tried(tmp_path):
    from manhwatok.app.chapter_post import pick_source
    from manhwatok.domain.models import ChapterSourceName

    messages: list[str] = []
    ct = _both(tmp_path, webtoons=(CH12,), error=MetadataError("MangaDex is down"))
    picked = pick_source(BOXER, ct, progress=messages.append)
    assert picked.source is ChapterSourceName.WEBTOONS
    assert any("MangaDex is down" in m for m in messages)


def test_what_each_source_listed_is_kept_apart(tmp_path):
    from manhwatok.app.chapter_post import refresh_chapters
    from manhwatok.domain.models import ChapterSourceName

    ct = _both(tmp_path, mangadex=(CH12,), webtoons=(CH12, CH13))
    refresh_chapters(BOXER, ct, NOW)
    refresh_chapters(BOXER, ct.using(ChapterSourceName.WEBTOONS), NOW)
    assert len(ct.chapters.chapters(119174, "en", ChapterSourceName.MANGADEX)) == 1
    assert len(ct.chapters.chapters(119174, "en", ChapterSourceName.WEBTOONS)) == 2


def test_the_post_records_which_source_its_chapter_came_from(tmp_path):
    from manhwatok.domain.models import ChapterSourceName

    ct = _both(tmp_path, webtoons=(CH12,)).using(ChapterSourceName.WEBTOONS)
    post, _ = _build(tmp_path, ct)
    assert post.chapter.source is ChapterSourceName.WEBTOONS


def test_chosen_part_takes_the_chapter_asked_for(tmp_path):
    ct = _chapter_tools(tmp_path, panels=40)
    _build(tmp_path, ct)  # chapter 12 part 1 of 2
    ct.pages.listings.clear()
    chosen = chosen_part(BOXER, ct, NOW, number="13")
    assert (chosen.part.chapter.number, chosen.part.part, chosen.built) == ("13", 1, False)
    assert ct.pages.listings == []  # the record had it


def test_chosen_part_says_a_part_was_built_already(tmp_path):
    ct = _chapter_tools(tmp_path, panels=40)
    _build(tmp_path, ct)
    chosen = chosen_part(BOXER, ct, NOW, number="12", part=1)
    assert (chosen.part.part, chosen.part.parts, chosen.built) == (1, 2, True)


def test_chosen_part_without_a_number_takes_the_next_part_of_the_next_chapter(tmp_path):
    ct = _chapter_tools(tmp_path, panels=40)
    _build(tmp_path, ct)
    chosen = chosen_part(BOXER, ct, NOW)
    assert (chosen.part.chapter.number, chosen.part.part, chosen.built) == ("12", 2, False)


def test_chosen_part_names_the_listed_chapters_for_one_that_is_missing(tmp_path):
    ct = _chapter_tools(tmp_path)
    with pytest.raises(ManhwatokError) as caught:
        chosen_part(BOXER, ct, NOW, number="99")
    assert "has no chapter 99 in en — listed: 12, 13" in str(caught.value)


def test_a_chapter_post_carries_its_accounts_byline(tmp_path):
    ct = _chapter_tools(tmp_path)
    account = Account(handle="reads", byline="manhwa daily · @reads")
    post, _ = build_chapter_post(BOXER, _tools(tmp_path), ct, account, NOW)
    assert post.byline == "manhwa daily · @reads"
