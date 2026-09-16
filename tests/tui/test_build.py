import pytest
import threading

pytest.importorskip("textual")

from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.errors import ManhwatokError  # noqa: E402
from manhwatok.domain.models import SearchQuery, Sort, TagInfo  # noqa: E402
from manhwatok.domain.theme import Theme  # noqa: E402
from manhwatok.tui.screens.build import BuildPane, matching_tags  # noqa: E402
from manhwatok.tui.screens.picks import PicksScreen  # noqa: E402
from manhwatok.tui.screens.posts import PostsPane  # noqa: E402
from tests.tui.helpers import NOW, make_ctx, notes, run_app, wait_for  # noqa: E402
from tests.unit.fakes import FakeMetadata, manhwa  # noqa: E402

CANDIDATES = [
    manhwa(anilist_id=11, title="Doom Breaker", description="Sent back ten years. More."),
    manhwa(anilist_id=22, title="Kubera", description="Gods. More."),
]
TAGS = [
    TagInfo(name="Revenge", category="Theme-Drama", description="Getting even."),
    TagInfo(name="Time Manipulation", category="Theme-Sci-Fi", description="Loops, revenge too."),
    TagInfo(name="Harem", category="Theme-Romance"),
]
REVENGE = Theme(name="revenge", tags=["Revenge"], title="MC gets *revenge*", sort=Sort.POPULARITY)


def _ctx(tmp_path, results=CANDIDATES):
    meta = FakeMetadata(results, tags=TAGS)
    ctx = make_ctx(tmp_path, metadata=meta)
    ctx.store.accounts.add(Account(handle="reads", hashtags="#reads", song="Acct Song"))
    ctx.store.themes.add(REVENGE)
    return ctx, meta


async def _open_build(app, pilot):
    await pilot.press("2")
    await pilot.pause()
    return app.query_one(BuildPane)


def _field(pane, name):
    return pane.query_one(f"#{name}")


async def _set(pilot, pane, **values):
    for name, value in values.items():
        _field(pane, name).value = value
    await pilot.pause()


def test_build_from_a_theme_for_an_account(tmp_path):
    ctx, meta = _ctx(tmp_path)

    async def scenario(app, pilot):
        pane = await _open_build(app, pilot)
        await _set(pilot, pane, account="reads", theme="revenge", song="Own", limit="5")
        assert _field(pane, "title").value == "MC gets *revenge*"
        pane.search()
        await wait_for(pilot, lambda: isinstance(app.screen, PicksScreen))
        assert app.screen.heading == "New post for @reads"
        await pilot.press("ctrl+s")
        await wait_for(pilot, lambda: app.query_one("#tabs").active == "posts")
        posts = app.query_one(PostsPane)
        assert posts.current is not None and posts.current.account == "reads"

    run_app(ctx, scenario)
    [query] = meta.queries
    assert (query.tags, query.sort, query.limit) == (["Revenge"], Sort.POPULARITY, 5)
    [saved] = ctx.tools.posts.list()
    assert (saved.title, saved.hashtags, saved.song) == ("MC gets *revenge*", "#reads", "Own")
    assert [i.manhwa.anilist_id for i in saved.items] == [11, 22]
    assert [i.hook for i in saved.items] == ["Sent back ten years.", "Gods."]
    assert saved.created_at == NOW
    assert len(ctx.tools.renderer.calls) == 1


def test_build_from_tags_without_an_account(tmp_path):
    ctx, meta = _ctx(tmp_path)

    async def scenario(app, pilot):
        pane = await _open_build(app, pilot)
        await _set(
            pilot,
            pane,
            tags="Revenge, Harem",
            genres="Action",
            sort=Sort.TRENDING,
            **{"min-rank": "80", "title": "T", "accent": "#ABCDEF"},
        )
        pane.query_one("#chapters").value = False
        pane.search()
        await wait_for(pilot, lambda: isinstance(app.screen, PicksScreen))
        await pilot.press("ctrl+s")
        await wait_for(pilot, lambda: ctx.tools.posts.list() != [])

    run_app(ctx, scenario)
    [query] = meta.queries
    assert (query.tags, query.genres, query.sort, query.min_tag_rank, query.limit) == (
        ["Revenge", "Harem"],
        ["Action"],
        Sort.TRENDING,
        80,
        12,
    )
    [saved] = ctx.tools.posts.list()
    assert (saved.account, saved.accent, saved.song) == (None, "#abcdef", None)
    assert ctx.chapters.calls == []


@pytest.mark.parametrize(
    "values, message",
    [
        ({}, "pick a theme or give at least one tag or genre"),
        ({"theme": "revenge", "tags": "Harem"}, "use either a theme or tags/genres, not both"),
        ({"tags": "Revenge", "limit": "51"}, "How many must be a whole number from 1 to 50"),
        (
            {"tags": "Revenge", "min-rank": "101"},
            "Min tag rank must be a whole number from 0 to 100",
        ),
        ({"tags": "Revenge", "accent": "cyan"}, "accent must look like #43c9e4"),
    ],
)
def test_search_checks_the_form_first(tmp_path, values, message):
    ctx, meta = _ctx(tmp_path)

    async def scenario(app, pilot):
        pane = await _open_build(app, pilot)
        await _set(pilot, pane, **values)
        pane.search()
        await pilot.pause()
        assert any(n.startswith(message) for n in notes(app)), notes(app)

    run_app(ctx, scenario)
    assert meta.queries == []


def test_no_matches(tmp_path):
    ctx, _ = _ctx(tmp_path, results=[])

    async def scenario(app, pilot):
        pane = await _open_build(app, pilot)
        await _set(pilot, pane, tags="Revenge")
        await pilot.click("#search")
        status = pane.query_one("#status")
        await wait_for(pilot, lambda: "no matches" in str(status.render()))
        assert not isinstance(app.screen, PicksScreen)

    run_app(ctx, scenario)


def test_cancelling_the_picks_saves_nothing(tmp_path):
    ctx, _ = _ctx(tmp_path)

    async def scenario(app, pilot):
        pane = await _open_build(app, pilot)
        await _set(pilot, pane, tags="Revenge", title="T")
        pane.search()
        await wait_for(pilot, lambda: isinstance(app.screen, PicksScreen))
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_one("#tabs").active == "build"

    run_app(ctx, scenario)
    assert ctx.tools.posts.list() == []


def test_the_theme_fills_the_title_unless_you_typed_one(tmp_path):
    ctx, _ = _ctx(tmp_path)
    ctx.store.themes.add(Theme(name="other", genres=["Action"], title="Other *title*"))

    async def scenario(app, pilot):
        pane = await _open_build(app, pilot)
        title = _field(pane, "title")
        await _set(pilot, pane, theme="revenge")
        assert title.value == "MC gets *revenge*"
        assert _field(pane, "tags").placeholder == "from the theme"
        await _set(pilot, pane, theme="other")
        assert title.value == "Other *title*"
        await _set(pilot, pane, title="Mine")
        await _set(pilot, pane, theme="revenge")
        assert title.value == "Mine"
        _field(pane, "theme").clear()
        await pilot.pause()
        assert title.value == "Mine"
        assert _field(pane, "tags").placeholder == ""

    run_app(ctx, scenario)


def test_blank_style_fields_show_the_accounts_values(tmp_path):
    ctx, _ = _ctx(tmp_path)

    async def scenario(app, pilot):
        pane = await _open_build(app, pilot)
        assert _field(pane, "song").placeholder == "no song"
        await _set(pilot, pane, account="reads")
        assert _field(pane, "hashtags").placeholder == "#reads"
        assert _field(pane, "accent").placeholder == "#43c9e4"
        assert _field(pane, "song").placeholder == "Acct Song (the account's)"

    run_app(ctx, scenario)


def test_accounts_and_themes_added_elsewhere_show_up(tmp_path):
    ctx, _ = _ctx(tmp_path)

    async def scenario(app, pilot):
        pane = await _open_build(app, pilot)
        await _set(pilot, pane, account="reads")
        ctx.store.accounts.add(Account(handle="later"))
        await pilot.press("1")
        await pilot.press("2")
        await pilot.pause()
        account = _field(pane, "account")
        assert [v for _, v in account._options[1:]] == ["later", "reads"]
        assert account.selection == "reads"

    run_app(ctx, scenario)


def test_tag_search_adds_tags(tmp_path):
    ctx, _ = _ctx(tmp_path)

    async def scenario(app, pilot):
        pane = await _open_build(app, pilot)
        await _set(pilot, pane, tags="Harem")
        _field(pane, "tag-search").focus()
        await pilot.press(*"reve")
        hits = pane.query_one("#tag-hits")
        await wait_for(pilot, lambda: hits.option_count == 2)
        assert [hits.get_option_at_index(i).id for i in range(2)] == [
            "Revenge",
            "Time Manipulation",
        ]
        await pilot.press("tab", "down", "down", "enter")  # nothing is highlighted at first
        await pilot.pause()
        assert _field(pane, "tags").value == "Harem, Time Manipulation"

    run_app(ctx, scenario)


def test_matching_tags():
    assert [t.name for t in matching_tags(TAGS, " REV ")] == ["Revenge", "Time Manipulation"]
    assert matching_tags(TAGS, "") == []
    many = [TagInfo(name=f"Tag {i}", category="x") for i in range(40)]
    assert len(matching_tags(many, "tag")) == 30


class BlockingMetadata(FakeMetadata):
    """FakeMetadata whose search() has per-call events; first call raises."""

    def __init__(self, results=(), tags=(), genres=()):
        super().__init__(results, tags, genres)
        self.events: dict[str, threading.Event] = {}

    def search(self, query: SearchQuery):
        self.queries.append(query)
        call_num = len(self.queries)
        event_key = f"call_{call_num}"
        if event_key not in self.events:
            self.events[event_key] = threading.Event()
        self.events[event_key].wait()
        if call_num == 1:
            raise ManhwatokError("first search failed")
        return list(self.results)


def test_cancelled_search_error_not_shown(tmp_path):
    """When a search is cancelled by a second search, the first's error doesn't appear."""
    meta = BlockingMetadata(CANDIDATES, tags=TAGS)
    # Create a new context with the blocking metadata
    from tests.tui.helpers import make_ctx as make_test_ctx
    ctx = make_test_ctx(tmp_path, metadata=meta)
    ctx.store.accounts.add(Account(handle="reads", hashtags="#reads", song="Acct Song"))
    ctx.store.themes.add(REVENGE)

    async def scenario(app, pilot):
        try:
            pane = await _open_build(app, pilot)
            await _set(pilot, pane, tags="Revenge")
            pane.search()
            await pilot.pause()
            # Start a second search immediately (before first completes); this cancels the first
            pane.search()
            await pilot.pause()
            # Release the first search so it can fail (but it's already cancelled)
            meta.events["call_1"].set()
            await pilot.pause()
            # Verify the first search's error never appeared in notifications
            assert not any("first search failed" in str(n) for n in notes(app))
            # Now release the second search which should succeed
            meta.events["call_2"].set()
            await wait_for(pilot, lambda: isinstance(app.screen, PicksScreen))
        finally:
            # Ensure all pending events are released so the app can shut down
            for event in meta.events.values():
                event.set()

    run_app(ctx, scenario)


def test_tag_loading_called_once_during_typing(tmp_path):
    """list_tags is called only once even when typing several characters."""

    class SlowMetadata(FakeMetadata):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.list_tags_calls = 0
            self.event = threading.Event()

        def list_tags(self):
            self.list_tags_calls += 1
            self.event.wait()
            if self.list_tags_calls == 1:
                return []  # First call returns empty, then event is released
            return list(self.tags)

    ctx, _ = _ctx(tmp_path)
    ctx.metadata = SlowMetadata(tags=TAGS)

    async def scenario(app, pilot):
        pane = await _open_build(app, pilot)
        tag_search = _field(pane, "tag-search")
        tag_search.focus()
        # Type "rev" - should trigger one tag load
        await pilot.press(*"rev")
        await pilot.pause()
        # While loading, type more characters - should not trigger more loads
        await pilot.press(*"eng")
        await pilot.pause()
        # Release the first and only list_tags call
        ctx.metadata.event.set()
        await wait_for(pilot, lambda: pane._tags is not None)
        # Verify only one call was made
        assert ctx.metadata.list_tags_calls == 1
        # Verify no error notifications appeared
        assert not any("error" in str(n).lower() for n in notes(app))

    run_app(ctx, scenario)


def test_list_tags_error_shown_once(tmp_path):
    """When list_tags fails, the error shows exactly once; retrying after fix shows tags."""

    class BlockingErrorMetadata(FakeMetadata):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.should_fail = True
            self.list_tags_calls = 0
            self.event = threading.Event()

        def list_tags(self):
            self.list_tags_calls += 1
            self.event.wait()
            if self.should_fail:
                raise ManhwatokError("AniList unreachable: boom")
            return list(self.tags)

    ctx, _ = _ctx(tmp_path)
    ctx.metadata = BlockingErrorMetadata(tags=TAGS)

    async def scenario(app, pilot):
        pane = await _open_build(app, pilot)
        tag_search = _field(pane, "tag-search")
        tag_search.focus()
        # Type to trigger list_tags (without waiting, so keystroke happens while load is pending)
        await pilot.press(*"rev")
        await pilot.pause()
        # Verify only one load was started
        assert ctx.metadata.list_tags_calls == 1
        # Release the load, let it fail
        ctx.metadata.event.set()
        await wait_for(pilot, lambda: "AniList unreachable" in str(notes(app)))
        error_notes = [n for n in notes(app) if "AniList unreachable" in str(n)]
        assert len(error_notes) == 1
        # Verify the loading flag was cleared so we can try again
        assert not pane._loading_tags
        # Fix the fake and reset for next attempt
        ctx.metadata.should_fail = False
        ctx.metadata.event.clear()
        # Type again to trigger another load
        await pilot.press(*"enge")
        # Release the second load
        ctx.metadata.event.set()
        await wait_for(pilot, lambda: pane._tags is not None)
        # Verify only 2 calls total (1 failing, 1 succeeding)
        assert ctx.metadata.list_tags_calls == 2
        # Verify no additional error notifications appeared
        assert len([n for n in notes(app) if "AniList unreachable" in str(n)]) == 1
        # Verify the tags loaded
        assert pane._tags == list(TAGS)

    run_app(ctx, scenario)
