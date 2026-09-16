import pytest

pytest.importorskip("textual")

from manhwatok.domain.errors import ManhwatokError  # noqa: E402
from manhwatok.domain.models import Sort, TagInfo  # noqa: E402
from manhwatok.domain.theme import Theme  # noqa: E402
from manhwatok.tui.screens.themes import ThemesPane, theme_fields, theme_texts  # noqa: E402
from manhwatok.tui.widgets.form import FormModal  # noqa: E402
from tests.tui.helpers import make_ctx, notes, run_app, wait_for  # noqa: E402
from tests.unit.fakes import FakeMetadata  # noqa: E402

REVENGE = Theme(name="revenge", tags=["Revenge"], title="MC gets *revenge*")


def _ctx(tmp_path):
    meta = FakeMetadata(
        tags=[TagInfo(name="Revenge", category="T"), TagInfo(name="Murim", category="T")],
        genres=["Action", "Fantasy"],
    )
    return make_ctx(tmp_path, metadata=meta)


def _rows(app):
    table = app.query_one(ThemesPane).query_one("DataTable")
    return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


async def _open(app, pilot):
    await pilot.press("4")
    await pilot.pause()


async def _fill(app, pilot, **values):
    for name, value in values.items():
        app.screen.query_one(f"#field-{name}").value = value
    await pilot.press("ctrl+s")


def test_add_a_theme(tmp_path):
    ctx = _ctx(tmp_path)

    async def scenario(app, pilot):
        await _open(app, pilot)
        assert "no themes yet" in str(app.query_one("#themes-hint").render())
        await pilot.press("a")
        await pilot.pause()
        await _fill(app, pilot, name="Murim-Kings", title="*Murim* kings", tags="murim")
        await wait_for(pilot, lambda: "added theme murim-kings" in notes(app))
        assert _rows(app) == [["murim-kings", "Murim kings", "Murim", "-", "score", "60"]]

    run_app(ctx, scenario)
    assert ctx.store.themes.get("murim-kings").tags == ["Murim"]


@pytest.mark.parametrize(
    "values, message",
    [
        ({"name": "bad name", "title": "T", "tags": "Murim"}, "'bad name' is not a theme name"),
        ({"name": "x", "title": "T"}, "theme x: give at least one tag or genre"),
        ({"name": "x", "title": "T", "tags": "Murim", "sort": "best"}, "sort must be one of"),
        ({"name": "x", "title": "T", "tags": "Mrim"}, "unknown tag 'Mrim'"),
    ],
)
def test_a_bad_theme_keeps_the_form_open(tmp_path, values, message):
    ctx = _ctx(tmp_path)

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("a")
        await pilot.pause()
        await _fill(app, pilot, **values)
        await wait_for(pilot, lambda: any(n.startswith(message) for n in notes(app)))
        assert isinstance(app.screen, FormModal)

    run_app(ctx, scenario)
    assert ctx.store.themes.list() == []


def test_edit_and_remove_a_theme(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.store.themes.add(REVENGE)

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("e")
        await pilot.pause()
        assert app.screen.form_title == "Edit theme revenge"
        await _fill(app, pilot, sort="Trending", genres="action")
        await wait_for(pilot, lambda: "saved theme revenge" in notes(app))
        assert _rows(app)[0][3:5] == ["Action", "trending"]
        await pilot.press("d")
        await pilot.pause()
        question = str(app.screen.query_one("#question").render())
        assert question == "Remove theme revenge? Posts built from it stay."
        await pilot.press("y")
        await pilot.pause()
        assert _rows(app) == []

    run_app(ctx, scenario)
    assert ctx.store.themes.list() == []


def test_theme_fields():
    before = theme_texts(REVENGE)
    assert before == {
        "title": "MC gets *revenge*",
        "tags": "Revenge",
        "genres": "",
        "sort": "score",
        "min_tag_rank": "60",
    }
    assert theme_fields(before, before) == {}
    assert theme_fields({**before, "min_tag_rank": "70"}, before) == {"min_tag_rank": 70}
    blank = {name: "" for name in before}
    assert theme_fields(blank, None) == {
        "title": "",
        "tags": [],
        "genres": [],
        "sort": Sort.SCORE,
        "min_tag_rank": 60,
    }
    with pytest.raises(ManhwatokError, match="min tag rank must be a whole number"):
        theme_fields({**before, "min_tag_rank": "high"}, before)
