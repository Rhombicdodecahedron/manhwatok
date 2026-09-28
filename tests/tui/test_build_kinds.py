import pytest

pytest.importorskip("textual")

from manhwatok.domain.models import PostKind  # noqa: E402
from manhwatok.tui.screens.build import BuildPane  # noqa: E402
from tests.tui.helpers import make_ctx, run_app  # noqa: E402
from tests.tui.test_build_chapter import _shown  # noqa: E402


@pytest.mark.parametrize("kind", ["similar", "versus", "guess", "characters"])
def test_each_kind_uses_the_list_form(tmp_path, kind):
    ctx = make_ctx(tmp_path)

    async def scenario(app, pilot):
        await pilot.press("2")
        await pilot.pause()
        pane = app.query_one(BuildPane)
        pane.query_one(f"#mode-{kind}").value = True
        await pilot.pause()
        assert pane.kind is PostKind(kind)
        assert _shown(pane, "search") and not _shown(pane, "chapter-build")
        assert _shown(pane, "like") is (kind == "similar")

    run_app(ctx, scenario)


def test_chapter_mode_still_swaps_the_form(tmp_path):
    ctx = make_ctx(tmp_path)

    async def scenario(app, pilot):
        await pilot.press("2")
        await pilot.pause()
        pane = app.query_one(BuildPane)
        pane.query_one("#mode-chapter").value = True
        await pilot.pause()
        assert pane.kind is PostKind.CHAPTER and pane.chapter_mode
        assert _shown(pane, "chapter-build") and not _shown(pane, "search")

    run_app(ctx, scenario)


def test_the_picks_screen_checks_the_kinds_rules_before_closing(tmp_path):
    from manhwatok.domain.post import PostItem
    from manhwatok.tui.screens.picks import PicksScreen
    from tests.unit.fakes import manhwa

    ctx = make_ctx(tmp_path)
    titles = [manhwa(anilist_id=i, title=f"T{i}") for i in (1, 2, 3)]
    results = []

    async def scenario(app, pilot):
        screen = PicksScreen("h", "T", [PostItem(manhwa=m) for m in titles], titles, PostKind.VERSUS)
        app.push_screen(screen, results.append)
        await pilot.pause()
        screen.action_save()
        await pilot.pause()
        assert app.screen is screen  # still open: three titles don't pair up

    run_app(ctx, scenario)
    assert results == []
