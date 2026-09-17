import pytest

pytest.importorskip("textual")

from manhwatok.app.login_account import quit_shortcut
from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.errors import ManhwatokError, MetadataError  # noqa: E402
from manhwatok.domain.models import ArtStyle, TagInfo  # noqa: E402
from manhwatok.tui.screens.accounts import (  # noqa: E402
    LABELS,
    AccountsPane,
    account_fields,
    account_texts,
)
from manhwatok.tui.screens.browser import BrowserScreen  # noqa: E402
from manhwatok.tui.widgets.dialogs import ConfirmModal  # noqa: E402
from manhwatok.tui.widgets.form import FormModal  # noqa: E402
from tests.tui.helpers import make_ctx, notes, run_app, wait_for  # noqa: E402
from tests.unit.fakes import FakeMetadata, FakeUploader  # noqa: E402

GENRES = ["Action", "Fantasy", "Romance"]
TAGS = [TagInfo(name="Harem", category="Theme")]


class Down(FakeMetadata):
    def list_genres(self):
        raise MetadataError("AniList unreachable: boom")


def _ctx(tmp_path, metadata=None, uploader=None):
    meta = metadata or FakeMetadata(tags=TAGS, genres=GENRES)
    return make_ctx(tmp_path, metadata=meta, uploader=uploader)


def _rows(app):
    table = app.query_one(AccountsPane).query_one("DataTable")
    return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


async def _open(app, pilot):
    await pilot.press("3")
    await pilot.pause()


async def _fill(app, pilot, **values):
    form = app.screen
    assert isinstance(form, FormModal)
    for name, value in values.items():
        form.query_one(f"#field-{name}").value = value
    await pilot.press("ctrl+s")


def test_add_an_account_in_anilist_spelling(tmp_path):
    ctx = _ctx(tmp_path)

    async def scenario(app, pilot):
        await _open(app, pilot)
        assert "no accounts yet — press a to add one" in str(
            app.query_one("#accounts-hint").render()
        )
        await pilot.press("a")
        await pilot.pause()
        await _fill(
            app,
            pilot,
            handle="@Reads",
            genres="action, fantasy",
            block_tags="harem",
            emojis=" 🔥📚 ",
            sounds="Dark Aria |  night drive | ",
            art="Panel",
            repeat_days="7",
        )
        await wait_for(pilot, lambda: not isinstance(app.screen, FormModal))
        assert "added @reads" in notes(app)
        assert _rows(app) == [
            [
                "@reads",
                "Action, Fantasy",
                "Harem",
                "#manhwa #manhwarecommendation…",
                "#43c9e4",
                "2 sounds",
                "panel",
                "7d",
                "-",
            ],
        ]

    run_app(ctx, scenario)
    a = ctx.store.accounts.get("reads")
    assert (a.genres, a.block_tags, a.repeat_days) == (["Action", "Fantasy"], ["Harem"], 7)
    assert (a.emojis, a.sounds, a.art) == ("🔥📚", ["Dark Aria", "night drive"], ArtStyle.PANEL)


def test_a_bad_field_keeps_the_form_open(tmp_path):
    ctx = _ctx(tmp_path)

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("a")
        await pilot.pause()
        await _fill(app, pilot, handle="reads", genres="Actoin")
        await wait_for(pilot, lambda: any("did you mean Action?" in n for n in notes(app)))
        await pilot.pause()
        assert isinstance(app.screen, FormModal)
        await _fill(app, pilot, genres="Action")
        await wait_for(pilot, lambda: not isinstance(app.screen, FormModal))

    run_app(ctx, scenario)
    assert ctx.store.accounts.get("reads").genres == ["Action"]


def test_anilist_down_warns_and_saves_as_typed(tmp_path):
    ctx = _ctx(tmp_path, metadata=Down())

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("a")
        await pilot.pause()
        await _fill(app, pilot, handle="reads", genres="Actoin")
        await wait_for(pilot, lambda: not isinstance(app.screen, FormModal))
        assert any(
            n.startswith("warning: couldn't check names against AniList") for n in notes(app)
        )

    run_app(ctx, scenario)
    assert ctx.store.accounts.get("reads").genres == ["Actoin"]


def test_edit_changes_only_what_changed(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.store.accounts.add(
        Account(
            handle="reads",
            genres=["Actoin"],
            hashtags="#old",
            emojis="📚",
            sounds=["Dark Aria", "night drive"],
            art=ArtStyle.BACKGROUND,
        )
    )

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        form = app.screen
        assert form.form_title == "Edit @reads"
        assert form.query_one("#field-genres").value == "Actoin"  # not re-checked: unchanged
        assert form.query_one("#field-sounds").value == "Dark Aria | night drive"
        assert form.query_one("#field-emojis").value == "📚"
        assert form.query_one("#field-art").value == "background"
        await _fill(app, pilot, hashtags="#new", sounds="Solo | Dark Aria", emojis="", art="")
        await wait_for(pilot, lambda: "saved @reads" in notes(app))
        assert _rows(app)[0][5:7] == ["2 sounds", "none"]

    run_app(ctx, scenario)
    a = ctx.store.accounts.get("reads")
    assert (a.genres, a.hashtags, a.sounds) == (["Actoin"], "#new", ["Solo", "Dark Aria"])
    assert (a.emojis, a.art) == ("", ArtStyle.NONE)


def test_the_table_shows_a_single_sound_clipped(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.store.accounts.add(Account(handle="reads", sounds=["SOLO LEVELING RaijinLofi remix"]))
    ctx.store.accounts.add(Account(handle="quiet"))

    async def scenario(app, pilot):
        await _open(app, pilot)
        assert [row[5:7] for row in _rows(app)] == [
            ["-", "none"],
            ["SOLO LEVELING RaijinLof…", "none"],
        ]

    run_app(ctx, scenario)


def test_a_sound_and_hashtag_with_brackets_render_verbatim_in_the_table(tmp_path):
    """User text (sounds, hashtags, genres...) must not be parsed as Rich markup: it must not
    crash the table, and must not be silently mangled (e.g. "[bold]" swallowed)."""
    ctx = _ctx(tmp_path)
    ctx.store.accounts.add(
        Account(handle="reads", sounds=["x [/] y"], hashtags="[bold]#h", genres=["Action"])
    )

    async def scenario(app, pilot):
        await _open(app, pilot)
        table = app.query_one(AccountsPane).query_one("DataTable")
        rendered = [str(c) for c in table._get_row_renderables(0).cells]
        assert rendered[3] == "[bold]#h"
        assert rendered[5] == "x [/] y"

    run_app(ctx, scenario)


def test_an_unknown_art_style_keeps_the_form_open_and_lists_the_choices(tmp_path):
    ctx = _ctx(tmp_path)

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("a")
        await pilot.pause()
        await _fill(app, pilot, handle="reads", art="epic")
        message = "art must be one of: none, background, panel, character"
        await wait_for(pilot, lambda: any(n.startswith(message) for n in notes(app)))
        await pilot.pause()
        assert isinstance(app.screen, FormModal)

    run_app(ctx, scenario)
    assert ctx.store.accounts.list() == []


def test_escape_cancels_the_form(tmp_path):
    ctx = _ctx(tmp_path)

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, FormModal)

    run_app(ctx, scenario)
    assert ctx.store.accounts.list() == []


def test_login_opens_the_accounts_browser(tmp_path):
    uploader = FakeUploader()
    ctx = _ctx(tmp_path, uploader=uploader)
    ctx.store.accounts.add(Account(handle="reads"))

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("l")
        await wait_for(pilot, lambda: isinstance(app.screen, BrowserScreen))
        log = app.screen.query_one("Log")
        await wait_for(pilot, lambda: "done — press escape to go back" in log.lines)
        assert list(log.lines)[:2] == [
            f"Log in to @reads in the Chrome window, then quit that Chrome ({quit_shortcut()}).",
            "browser closed — once logged in, uploads post as @reads",
        ]
        (tmp_path / "browser" / "reads").mkdir(parents=True)  # what a real login leaves
        await pilot.press("escape")
        await pilot.pause()
        assert _rows(app)[0][-1] == "saved"

    run_app(ctx, scenario)
    assert uploader.events == ["login", "close"]
    assert uploader.logins == ["reads"]


@pytest.mark.parametrize("forget", [True, False])
def test_remove_keeps_history_and_offers_to_forget_the_login(tmp_path, forget):
    ctx = _ctx(tmp_path)
    ctx.store.accounts.add(Account(handle="reads"))
    profile = tmp_path / "browser" / "reads"
    profile.mkdir(parents=True)

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("d")
        await pilot.pause()
        question = str(app.screen.query_one("#question").render())
        assert question == "Remove @reads? Its posting history is kept."
        await pilot.press("y")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        question = str(app.screen.query_one("#question").render())
        assert question == "Also delete the saved TikTok login for @reads?"
        await pilot.press("y" if forget else "n")
        await pilot.pause()
        assert _rows(app) == []

    run_app(ctx, scenario)
    assert ctx.store.accounts.list() == []
    assert profile.exists() is not forget


def test_remove_can_be_declined(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.store.accounts.add(Account(handle="reads"))

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert len(_rows(app)) == 1

    run_app(ctx, scenario)


def test_sounds_label_warns_that_a_sound_cant_contain_a_pipe():
    assert "|" in LABELS["sounds"]
    assert "can't contain |" in LABELS["sounds"]


def test_editing_an_account_with_a_piped_sound_warns_but_keeps_it_if_untouched(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.store.accounts.add(Account(handle="reads", sounds=["clean", "weird|sound"]))

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert (
            "sound 'weird|sound' contains | — edit it with manhwatok account set --sound"
            in notes(app)
        )
        await _fill(app, pilot, hashtags="#new")
        await wait_for(pilot, lambda: "saved @reads" in notes(app))

    run_app(ctx, scenario)
    a = ctx.store.accounts.get("reads")
    assert a.sounds == ["clean", "weird|sound"]
    assert a.hashtags == "#new"


def test_account_fields():
    before = account_texts(Account(handle="reads", genres=["Action"], sounds=["S"]))
    assert before["genres"] == "Action" and before["repeat_days"] == "30"
    assert (before["sounds"], before["emojis"], before["art"]) == ("S", "", "")
    assert account_fields({**before, "handle": "x"}, before) == {}
    changed = {**before, "genres": "", "repeat_days": "7", "sounds": ""}
    assert account_fields(changed, before) == {"genres": [], "repeat_days": 7, "sounds": []}
    new = {name: "" for name in before} | {"hashtags": "#h", "block_tags": "A, B"}
    assert account_fields(new, None) == {"hashtags": "#h", "block_tags": ["A", "B"]}
    with pytest.raises(ManhwatokError, match="repeat days must be a whole number"):
        account_fields({**before, "repeat_days": "soon"}, before)


def test_account_fields_sounds_emojis_and_art():
    before = account_texts(Account(handle="reads"))
    texts = {**before, "sounds": " a | b |  | c ", "emojis": "🔥", "art": " Character "}
    assert account_fields(texts, before) == {
        "sounds": ["a", "b", "c"],
        "emojis": "🔥",
        "art": ArtStyle.CHARACTER,
    }
    styled = account_texts(Account(handle="reads", sounds=["a", "b"], art=ArtStyle.PANEL))
    assert (styled["sounds"], styled["art"]) == ("a | b", "panel")
    assert account_fields({**styled, "art": ""}, styled) == {"art": ArtStyle.NONE}
    with pytest.raises(ManhwatokError, match="art must be one of: none, background, panel"):
        account_fields({**before, "art": "epic"}, before)
