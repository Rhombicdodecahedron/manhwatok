import pytest

pytest.importorskip("textual")

from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.errors import ManhwatokError, MetadataError  # noqa: E402
from manhwatok.domain.models import TagInfo  # noqa: E402
from manhwatok.tui.screens.accounts import (  # noqa: E402
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
            song="Die For You",
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
                "Die For You",
                "7d",
                "-",
            ],
        ]

    run_app(ctx, scenario)
    a = ctx.store.accounts.get("reads")
    assert (a.genres, a.block_tags, a.song, a.repeat_days) == (
        ["Action", "Fantasy"],
        ["Harem"],
        "Die For You",
        7,
    )


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
    ctx.store.accounts.add(Account(handle="reads", genres=["Actoin"], hashtags="#old"))

    async def scenario(app, pilot):
        await _open(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        form = app.screen
        assert form.form_title == "Edit @reads"
        assert form.query_one("#field-genres").value == "Actoin"  # not re-checked: unchanged
        await _fill(app, pilot, hashtags="#new", song="Mine")
        await wait_for(pilot, lambda: "saved @reads" in notes(app))

    run_app(ctx, scenario)
    a = ctx.store.accounts.get("reads")
    assert (a.genres, a.hashtags, a.song) == (["Actoin"], "#new", "Mine")


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
            "Log in to @reads in the browser, then close the window.",
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


def test_account_fields():
    before = account_texts(Account(handle="reads", genres=["Action"], song="S"))
    assert before["genres"] == "Action" and before["repeat_days"] == "30"
    assert account_fields({**before, "handle": "x"}, before) == {}
    changed = {**before, "genres": "", "repeat_days": "7", "song": ""}
    assert account_fields(changed, before) == {"genres": [], "repeat_days": 7, "song": ""}
    new = {name: "" for name in before} | {"hashtags": "#h", "block_tags": "A, B"}
    assert account_fields(new, None) == {"hashtags": "#h", "block_tags": ["A", "B"]}
    with pytest.raises(ManhwatokError, match="repeat days must be a whole number"):
        account_fields({**before, "repeat_days": "soon"}, before)
