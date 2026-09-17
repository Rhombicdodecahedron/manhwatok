import pytest

pytest.importorskip("textual")

from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.domain.post import MAX_ITEMS, PostItem  # noqa: E402
from manhwatok.tui.screens.picks import PicksScreen  # noqa: E402
from manhwatok.tui.widgets.dialogs import ConfirmModal  # noqa: E402
from tests.tui.helpers import make_ctx, notes, run_app, wait_for  # noqa: E402
from tests.unit.fakes import FakeCovers, cover_file, manhwa, post  # noqa: E402

CANDIDATES = [
    manhwa(anilist_id=i, title=f"Title {i}", description=f"Hook {i}. More.") for i in (1, 2, 3, 4)
]
START = [PostItem(manhwa=CANDIDATES[0], hook="Mine 1"), PostItem(manhwa=CANDIDATES[1])]


def _open(app, results, title="T", items=START, candidates=CANDIDATES):
    app.push_screen(PicksScreen("New post", title, items, candidates), results.append)


def _ids(result):
    title, items = result
    return title, [(i.manhwa.anilist_id, i.hook) for i in items]


def _table(app, name):
    table = app.screen.query_one(f"#{name}")
    return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


def test_pick_unpick_reorder_and_save(tmp_path):
    results = []

    async def scenario(app, pilot):
        _open(app, results)
        await pilot.pause()
        assert [r[1] for r in _table(app, "picks")] == ["Title 1", "Title 2"]
        assert [r[0] for r in _table(app, "others")] == ["Title 3", "Title 4"]
        await pilot.press("tab", "down", "space")  # others: pick Title 4
        await pilot.press("shift+tab", "space")  # picks: drop Title 1 (cursor on the first row)
        assert [r[0] for r in _table(app, "others")] == ["Title 1", "Title 3"]
        await pilot.press("down", "shift+up")  # Title 4 above Title 2
        await pilot.press("tab", "space")  # others: bring Title 1 back, with its own hook
        await pilot.press("ctrl+s")
        await pilot.pause()

    run_app(make_ctx(tmp_path), scenario)
    assert [_ids(r) for r in results] == [
        ("T", [(4, "Hook 4."), (2, ""), (1, "Mine 1")]),
    ]


def test_enter_edits_the_hook(tmp_path):
    results = []

    async def scenario(app, pilot):
        _open(app, results)
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()
        await pilot.press(*"Better", "enter")
        await pilot.pause()
        assert _table(app, "picks")[1][3] == "Better"
        await pilot.press("ctrl+s")
        await pilot.pause()

    run_app(make_ctx(tmp_path), scenario)
    assert _ids(results[0]) == ("T", [(1, "Mine 1"), (2, "Better")])


def test_the_title_is_edited_in_its_input(tmp_path):
    results = []

    async def scenario(app, pilot):
        _open(app, results)
        await pilot.pause()
        await pilot.press("shift+tab", *"New *title*", "ctrl+s")  # typing replaces the old title
        await pilot.pause()

    run_app(make_ctx(tmp_path), scenario)
    assert _ids(results[0])[0] == "New *title*"


@pytest.mark.parametrize(
    "title, items, message",
    [(" ", START, "give the post a title"), ("T", [], "pick at least one title")],
)
def test_save_checks_the_picks(tmp_path, title, items, message):
    results = []

    async def scenario(app, pilot):
        _open(app, results, title=title, items=items)
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert message in notes(app)
        assert isinstance(app.screen, PicksScreen)

    run_app(make_ctx(tmp_path), scenario)
    assert results == []


def test_a_bracketed_title_renders_verbatim_and_the_hook_editor_shows_it_too(tmp_path):
    """A manhwa title with square brackets must not be parsed as markup: not crash the picks
    table, and the hook editor's prompt (built from that title) must show it verbatim too."""
    bracketed = manhwa(anilist_id=9, title="Solo Leveling [/] Uncut", description="Hook 9. More.")
    results = []

    async def scenario(app, pilot):
        _open(
            app,
            results,
            items=[PostItem(manhwa=bracketed)],
            candidates=[bracketed],
        )
        await pilot.pause()
        table = app.screen.query_one("#picks")
        rendered = str(table._get_row_renderables(0).cells[1])
        assert rendered == "Solo Leveling [/] Uncut"
        await pilot.press("enter")
        await pilot.pause()
        assert str(app.screen.query_one("Label").render()) == "Hook for Solo Leveling [/] Uncut"
        await pilot.press("escape")
        await pilot.pause()

    run_app(make_ctx(tmp_path), scenario)


def test_a_post_fits_at_most_max_items(tmp_path):
    many = [manhwa(anilist_id=i, title=f"T{i}") for i in range(MAX_ITEMS + 1)]
    results = []

    async def scenario(app, pilot):
        items = [PostItem(manhwa=m) for m in many[:MAX_ITEMS]]
        _open(app, results, items=items, candidates=many)
        await pilot.pause()
        await pilot.press("tab", "space")
        assert f"a TikTok post fits at most {MAX_ITEMS} titles" in notes(app)
        assert len(_table(app, "picks")) == MAX_ITEMS

    run_app(make_ctx(tmp_path), scenario)


def test_escape_without_changes_just_closes(tmp_path):
    results = []

    async def scenario(app, pilot):
        _open(app, results)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, PicksScreen)

    run_app(make_ctx(tmp_path), scenario)
    assert results == [None]


def test_escape_with_changes_asks_first(tmp_path):
    results = []

    async def scenario(app, pilot):
        _open(app, results)
        await pilot.pause()
        await pilot.press("space", "escape")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, PicksScreen)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

    run_app(make_ctx(tmp_path), scenario)
    assert results == [None]


def test_q_with_changes_asks_first_and_does_not_quit(tmp_path):
    results = []

    async def scenario(app, pilot):
        _open(app, results)
        await pilot.pause()
        await pilot.press("space", "q")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        assert app.is_running
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, PicksScreen)
        assert app.is_running
        await pilot.press("q")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert app.is_running

    run_app(make_ctx(tmp_path), scenario)
    assert results == [None]


def test_q_without_changes_closes_the_editor(tmp_path):
    results = []

    async def scenario(app, pilot):
        _open(app, results)
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen, PicksScreen)
        assert app.is_running

    run_app(make_ctx(tmp_path), scenario)
    assert results == [None]


def test_number_keys_do_nothing_on_the_picks_editor(tmp_path):
    """1-4 must not leak through to the app's tab-switching bindings while the editor is
    open — even though switching tabs wouldn't itself change which screen is on top, it would
    silently change the tab waiting underneath once the editor closes."""
    results = []

    async def scenario(app, pilot):
        _open(app, results)
        await pilot.pause()
        before = app.query_one("#tabs").active
        for key in ("2", "3", "4", "1"):
            await pilot.press(key)
            await pilot.pause()
            assert app.query_one("#tabs").active == before
        assert isinstance(app.screen, PicksScreen)

    run_app(make_ctx(tmp_path), scenario)
    assert results == []


def test_the_highlighted_titles_cached_cover_is_shown(tmp_path):
    path = cover_file(tmp_path / "covers", 2)
    covers = FakeCovers({2: path}, on_disk={2})

    async def scenario(app, pilot):
        _open(app, [])
        await pilot.pause()
        cover = app.screen.query_one("#cover")
        assert cover.image is None and not cover.display
        assert str(app.screen.query_one("#cover-info").render()).startswith("Title 1\nongoing")
        await pilot.press("down")
        assert cover.image == path and cover.display

    run_app(make_ctx(tmp_path, covers=covers), scenario)
    assert covers.calls == []  # never downloads


def test_edit_from_the_posts_list_saves_and_rerenders(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.tools.posts.save(post())
    render_post("20260914-a3f9", ctx.tools)

    async def scenario(app, pilot):
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, PicksScreen)
        await pilot.press("shift+down", "ctrl+s")
        await wait_for(pilot, lambda: any("saved · 5 slides" in n for n in notes(app)))

    run_app(ctx, scenario)
    saved = ctx.tools.posts.get("20260914-a3f9")
    assert [i.manhwa.anilist_id for i in saved.items] == [2, 1, 3]
    assert len(ctx.tools.renderer.calls) == 2
