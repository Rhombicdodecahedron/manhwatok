from datetime import datetime, timezone

import pytest

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.chapter_post import build_chapter_post
from manhwatok.app.context import AppContext
from manhwatok.app.next_post import make_next_post
from manhwatok.app.render_post import rendered_files
from manhwatok.config import Settings
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError, ThemeNotFound
from manhwatok.domain.models import ArtSourceName
from manhwatok.domain.theme import Theme
from manhwatok.ports.art import ArtOption
from manhwatok.ports.chapters import ChapterInfo
from tests.unit.fakes import (
    FakeArtSource,
    FakeChapterPages,
    FakeChapters,
    FakeCutter,
    FakeMetadata,
    make_chapter_tools,
    make_tools,
    manhwa,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
BOXER = manhwa(anilist_id=119174, title="The Boxer")
PICKS = [
    manhwa(anilist_id=i, title=f"Title {i}", description=f"Hook {i}. More.") for i in (1, 2, 3)
]
CH12 = ChapterInfo("ch-12", "12", "Talent", "en", 36)
ISEKAI = Theme(name="isekai", tags=["Isekai"], title="Manhwa where the MC is *reborn*")


@pytest.fixture
def store(tmp_path):
    with SqliteStore(tmp_path / "manhwatok.db") as s:
        s.themes.add(ISEKAI)
        yield s


class Catalogue(FakeMetadata):
    """AniList: finds BOXER by name, and answers every search with the picks."""

    def search(self, query):
        self.queries.append(query)
        return list(PICKS)


def _ctx(tmp_path, store, pins=None, chapters=(CH12,)) -> AppContext:
    """A context on a real database and post folders, fakes elsewhere."""
    pages = FakeChapterPages(chapters=list(chapters))
    return AppContext(
        settings=Settings(data_dir=tmp_path),
        store=store,
        metadata=Catalogue([BOXER, *PICKS]),
        chapters=FakeChapters(),
        tools=make_tools(tmp_path),
        art_sources={name: FakeArtSource() for name in ArtSourceName}
        | ({ArtSourceName.PINS: pins} if pins else {}),
        chapter_tools=make_chapter_tools(
            tmp_path, pages=pages, cutter=FakeCutter(4), chapters=store.chapters
        ),
        uploader_factory=lambda: None,
    )


def _account(store, rotation, **fields) -> Account:
    account = Account(handle="reads", rotation=rotation, **fields)
    store.accounts.add(account)
    return account


def test_a_theme_item_builds_a_list_post_with_the_first_picks_and_renders_it(tmp_path, store):
    ctx = _ctx(tmp_path, store)
    _account(store, ["theme:isekai", "chapter:The Boxer"], accent="#ff5a5f")

    post = make_next_post(ctx, "reads", NOW)

    assert post.theme == "isekai"
    assert post.title == ISEKAI.title
    assert post.account == "reads" and post.accent == "#ff5a5f"
    assert [i.manhwa.anilist_id for i in post.items] == [1, 2, 3]
    assert [i.hook for i in post.items] == ["Hook 1.", "Hook 2.", "Hook 3."]
    assert ctx.tools.posts.get(post.id) == post
    rendered_files(post, ctx.tools.posts)  # raises unless its slides are up to date
    assert store.accounts.get("reads").rotation_cursor == 1


def test_a_theme_item_searches_as_build_theme_does_for_the_account(tmp_path, store):
    ctx = _ctx(tmp_path, store)
    _account(store, ["theme:isekai"], block_tags=["Harem"])

    make_next_post(ctx, "reads", NOW)

    [query] = ctx.metadata.queries
    assert query.tags == ["Isekai"] and query.exclude_tags == ["Harem"]


def test_a_theme_item_fills_art_from_the_accounts_art_source(tmp_path, store):
    pins = FakeArtSource(
        {
            1: [ArtOption("pin 1", "https://x.test/1.jpg")],
            2: [ArtOption("pin 2", "https://x.test/2.jpg")],
        }
    )
    ctx = _ctx(tmp_path, store, pins=pins)
    _account(store, ["theme:isekai"], art_source="pins")

    post = make_next_post(ctx, "reads", NOW)

    assert pins.fetched == ["https://x.test/1.jpg", "https://x.test/2.jpg"]
    saved = ctx.tools.posts.get(post.id)
    assert [bool(i.custom_art) for i in saved.items] == [True, True, False]
    rendered_files(saved, ctx.tools.posts)


def test_without_an_art_source_no_art_is_searched(tmp_path, store):
    ctx = _ctx(tmp_path, store)
    _account(store, ["theme:isekai"])

    make_next_post(ctx, "reads", NOW)

    assert all(source.fetched == [] for source in ctx.art_sources.values())


def test_a_failed_art_search_keeps_no_half_made_post(tmp_path, store):
    ctx = _ctx(tmp_path, store, pins=FakeArtSource(error=ManhwatokError("Pinterest is down")))
    _account(store, ["theme:isekai"], art_source="pins")

    with pytest.raises(ManhwatokError, match="Pinterest is down"):
        make_next_post(ctx, "reads", NOW)

    assert ctx.tools.posts.list() == []
    assert store.accounts.get("reads").rotation_cursor == 0


def test_a_chapter_item_builds_the_titles_next_part_for_the_account(tmp_path, store):
    ctx = _ctx(tmp_path, store)
    _account(store, ["chapter:The Boxer", "theme:isekai"], hashtags="#boxing")

    post = make_next_post(ctx, "reads", NOW)

    assert post.chapter.anilist_id == BOXER.anilist_id
    assert (post.chapter.number, post.chapter.part) == ("12", 1)
    assert post.account == "reads" and post.hashtags == "#boxing"
    assert [p.post_id for p in store.chapters.parts(BOXER.anilist_id)] == [post.id]
    assert store.accounts.get("reads").rotation_cursor == 1


def test_the_cursor_wraps_around_after_the_last_item(tmp_path, store):
    ctx = _ctx(tmp_path, store)
    _account(store, ["chapter:The Boxer", "theme:isekai"], rotation_cursor=1)

    post = make_next_post(ctx, "reads", NOW)

    assert post.theme == "isekai"
    assert store.accounts.get("reads").rotation_cursor == 0


def test_calls_in_a_row_go_round_the_rotation(tmp_path, store):
    ctx = _ctx(tmp_path, store, chapters=(CH12, ChapterInfo("ch-13", "13", "", "en", 30)))
    _account(store, ["chapter:The Boxer", "theme:isekai"])

    made = [make_next_post(ctx, "reads", NOW) for _ in range(3)]

    assert [p.chapter.number if p.chapter else p.theme for p in made] == ["12", "isekai", "13"]


def _built_out(ctx):
    """Build The Boxer's only part, so the chapter item has nothing left."""
    build_chapter_post(BOXER, ctx.tools, ctx.chapter_tools, None, NOW)


def test_a_chapter_with_no_part_left_is_skipped_with_a_warning(tmp_path, store):
    ctx = _ctx(tmp_path, store)
    _account(store, ["chapter:The Boxer", "theme:isekai"])
    _built_out(ctx)
    pages = ctx.chapter_tools.pages
    listed = len(pages.listings)
    warnings = []

    post = make_next_post(ctx, "reads", NOW, warnings.append)

    assert post.theme == "isekai"
    assert warnings == [
        "The Boxer: every listed chapter is built — skipping to the next rotation item"
    ]
    assert len(pages.listings) == listed + 1  # asked the source for new chapters first
    assert store.accounts.get("reads").rotation_cursor == 0


def test_a_new_chapter_listed_since_is_built_rather_than_skipped(tmp_path, store):
    ctx = _ctx(tmp_path, store)
    _account(store, ["chapter:The Boxer", "theme:isekai"])
    _built_out(ctx)
    ctx.chapter_tools.pages.listed.append(ChapterInfo("ch-13", "13", "", "en", 30))
    warnings = []

    post = make_next_post(ctx, "reads", NOW, warnings.append)

    assert post.chapter.number == "13"
    assert warnings == []


def test_a_rotation_with_nothing_left_anywhere_gives_up_after_one_pass(tmp_path, store):
    ctx = _ctx(tmp_path, store)
    _account(store, ["chapter:The Boxer", "chapter:119174"], rotation_cursor=1)
    store.cache.put(f"manhwa:{BOXER.anilist_id}", BOXER.model_dump_json())  # named by id once
    _built_out(ctx)
    warnings = []

    with pytest.raises(ManhwatokError, match="nothing left to post in @reads's rotation"):
        make_next_post(ctx, "reads", NOW, warnings.append)

    assert len(warnings) == 2
    assert store.accounts.get("reads").rotation_cursor == 1


def test_a_failure_leaves_the_cursor_where_it_was(tmp_path, store):
    ctx = _ctx(tmp_path, store)
    _account(store, ["theme:gone", "theme:isekai"])

    with pytest.raises(ThemeNotFound):
        make_next_post(ctx, "reads", NOW)

    assert store.accounts.get("reads").rotation_cursor == 0
    assert ctx.tools.posts.list() == []


def test_an_account_without_a_rotation_is_told_how_to_set_one(tmp_path, store):
    ctx = _ctx(tmp_path, store)
    _account(store, [])

    with pytest.raises(ManhwatokError, match="--rotation"):
        make_next_post(ctx, "@reads", NOW)
