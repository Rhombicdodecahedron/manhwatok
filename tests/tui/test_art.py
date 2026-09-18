import pytest

pytest.importorskip("textual")

from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.ports.art import ArtOption  # noqa: E402
from manhwatok.tui.screens.art import ArtScreen  # noqa: E402
from tests.tui.helpers import Opened, make_ctx, notes, run_app, wait_for  # noqa: E402
from tests.unit.fakes import FakeArtSource, post  # noqa: E402

PID = "20260914-a3f9"
VOL1 = ArtOption("vol. 1", "https://x.test/1.jpg")
VOL2 = ArtOption("vol. 2", "https://x.test/2.jpg")


def _ready(tmp_path, art=None, fanart=None):
    ctx = make_ctx(tmp_path, art=art, fanart=fanart)
    ctx.tools.posts.save(post(id=PID))
    render_post(PID, ctx.tools)
    return ctx


def _table_rows(app, table_id):
    table = app.screen.query_one(f"#{table_id}")
    return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


def test_a_opens_the_art_screen_listing_the_posts_titles(tmp_path):
    ctx = _ready(tmp_path)

    async def scenario(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, ArtScreen)
        assert [row[0] for row in _table_rows(app, "titles")] == ["1", "2", "3"]

    run_app(ctx, scenario)


def test_choosing_a_title_lists_the_covers_the_source_has_for_it(tmp_path):
    ctx = _ready(tmp_path, art=FakeArtSource({1: [VOL1, VOL2]}))

    async def scenario(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("enter")
        await wait_for(pilot, lambda: _table_rows(app, "covers"))
        assert [row[1] for row in _table_rows(app, "covers")] == ["vol. 1", "vol. 2"]

    run_app(ctx, scenario)


def test_choosing_a_cover_downloads_it_and_records_it_as_that_titles_art(tmp_path):
    source = FakeArtSource({1: [VOL1, VOL2]})
    ctx = _ready(tmp_path, art=source)

    async def scenario(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("enter")
        await wait_for(pilot, lambda: _table_rows(app, "covers"))
        await pilot.press("down", "enter")
        await wait_for(pilot, lambda: ctx.tools.posts.get(PID).items[0].custom_art)

        assert source.fetched == [VOL2.url]
        assert ctx.tools.posts.get(PID).items[0].custom_art == "art-1.jpg"
        assert (ctx.tools.posts.folder(PID) / "art-1.jpg").is_file()

    run_app(ctx, scenario)


def test_says_so_when_the_source_has_no_covers_for_the_title(tmp_path):
    ctx = _ready(tmp_path, art=FakeArtSource({}))

    async def scenario(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("enter")
        await wait_for(pilot, lambda: any("no covers" in n.lower() for n in notes(app)))

    run_app(ctx, scenario)


async def _pick_first_cover(pilot, app):
    await pilot.press("a")
    await pilot.pause()
    await pilot.press("enter")
    await wait_for(pilot, lambda: _table_rows(app, "covers"))
    await pilot.press("enter")


def test_c_drops_the_picked_art_again(tmp_path):
    ctx = _ready(tmp_path, art=FakeArtSource({1: [VOL1]}))

    async def scenario(app, pilot):
        await _pick_first_cover(pilot, app)
        await wait_for(pilot, lambda: ctx.tools.posts.get(PID).items[0].custom_art)
        assert (ctx.tools.posts.folder(PID) / "art-1.jpg").is_file()

        await pilot.press("c")
        await wait_for(pilot, lambda: not ctx.tools.posts.get(PID).items[0].custom_art)
        assert not (ctx.tools.posts.folder(PID) / "art-1.jpg").exists()

    run_app(ctx, scenario)


def test_u_takes_a_file_path_typed_by_hand(tmp_path):
    ctx = _ready(tmp_path)
    mine = tmp_path / "mine.png"
    mine.write_bytes(b"\x89PNG pretend")

    async def scenario(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("u")
        await pilot.pause()
        for ch in str(mine):
            await pilot.press(ch if ch != "/" else "slash")
        await pilot.press("enter")
        await wait_for(pilot, lambda: ctx.tools.posts.get(PID).items[0].custom_art)

        assert ctx.tools.posts.get(PID).items[0].custom_art == "art-1.png"
        assert (ctx.tools.posts.folder(PID) / "art-1.png").read_bytes() == b"\x89PNG pretend"

    run_app(ctx, scenario)


def test_o_opens_the_picked_art_and_warns_when_there_is_none(tmp_path):
    ctx = _ready(tmp_path, art=FakeArtSource({1: [VOL1]}))
    opened = Opened()

    async def scenario(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert opened == []
        assert any("no picked art" in n for n in notes(app))

        await _pick_first_cover(pilot, app)
        await wait_for(pilot, lambda: ctx.tools.posts.get(PID).items[0].custom_art)
        await pilot.press("o")
        await pilot.pause()
        assert opened == [ctx.tools.posts.folder(PID) / "art-1.jpg"]

    run_app(ctx, scenario, opener=opened)


FAN1 = ArtOption("★ 99  900x1400  by someone", "https://x.test/fan.jpg")


def test_s_switches_between_covers_and_fan_art(tmp_path):
    ctx = _ready(
        tmp_path,
        art=FakeArtSource({1: [VOL1, VOL2]}),
        fanart=FakeArtSource({1: [FAN1]}),
    )

    async def scenario(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("enter")
        await wait_for(pilot, lambda: _table_rows(app, "covers"))
        assert [r[1] for r in _table_rows(app, "covers")] == ["vol. 1", "vol. 2"]

        await pilot.press("s")
        await wait_for(pilot, lambda: len(_table_rows(app, "covers")) == 1)
        assert [r[1] for r in _table_rows(app, "covers")] == [FAN1.label]

        await pilot.press("s")
        await wait_for(pilot, lambda: len(_table_rows(app, "covers")) == 2)

    run_app(ctx, scenario)


def test_fan_art_is_used_from_the_fan_art_source(tmp_path):
    fanart = FakeArtSource({1: [FAN1]})
    ctx = _ready(tmp_path, art=FakeArtSource({1: [VOL1]}), fanart=fanart)

    async def scenario(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await wait_for(pilot, lambda: _table_rows(app, "covers"))
        await pilot.press("enter")
        await wait_for(pilot, lambda: ctx.tools.posts.get(PID).items[0].custom_art)

        assert fanart.fetched == [FAN1.url]

    run_app(ctx, scenario)
