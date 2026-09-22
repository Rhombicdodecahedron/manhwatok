import sys
import threading

import pytest

pytest.importorskip("textual")

from typer.testing import CliRunner  # noqa: E402

from manhwatok.cli import app as cli  # noqa: E402
from manhwatok.domain.errors import ManhwatokError  # noqa: E402
from manhwatok.tui.widgets.dialogs import ChoiceModal, ConfirmModal, TextModal  # noqa: E402
from manhwatok.tui.widgets.form import FormModal  # noqa: E402
from tests.tui.helpers import make_ctx, notes, run_app, wait_for  # noqa: E402


def test_number_keys_switch_tabs_and_q_quits(tmp_path):
    async def scenario(app, pilot):
        tabs = app.query_one("#tabs")
        assert tabs.active == "posts"
        for key, tab in [("2", "build"), ("3", "accounts"), ("4", "themes"), ("5", "queue"), ("1", "posts")]:
            await pilot.press(key)
            assert tabs.active == tab
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running

    run_app(make_ctx(tmp_path), scenario)


@pytest.mark.parametrize(
    "keys, expected",
    [
        (["y"], True),
        (["n"], False),
        (["escape"], False),
        (["enter"], False),
        (["tab", "enter"], True),
    ],
)
def test_confirm_modal_defaults_to_no(tmp_path, keys, expected):
    answers = []

    async def scenario(app, pilot):
        app.push_screen(ConfirmModal("Sure?"), answers.append)
        await pilot.pause()
        await pilot.press(*keys)
        await pilot.pause()

    run_app(make_ctx(tmp_path), scenario)
    assert answers == [expected]


def test_text_and_choice_modals(tmp_path):
    answers = []

    async def scenario(app, pilot):
        app.push_screen(TextModal("Name?", value="old"), answers.append)
        await pilot.pause()
        await pilot.press("end", "backspace", "backspace", "backspace", *"  new  ", "enter")
        app.push_screen(TextModal("Name?"), answers.append)
        await pilot.pause()
        await pilot.press("escape")
        app.push_screen(ChoiceModal("Which?", [("All", "*"), ("@reads", "reads")]), answers.append)
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()

    run_app(make_ctx(tmp_path), scenario)
    assert answers == ["new", None, "reads"]


def test_one_render_at_a_time_and_errors_become_notifications(tmp_path):
    release = threading.Event()
    done = []

    def slow(tools):
        release.wait(5)
        return "slow"

    def broken(tools):
        raise ManhwatokError("disk full")

    async def scenario(app, pilot):
        assert app.start_render(slow, done.append)
        await wait_for(pilot, lambda: app.rendering)
        assert not app.start_render(slow, done.append)
        assert "still rendering — try again when it's done" in notes(app)
        release.set()
        await wait_for(pilot, lambda: done == ["slow"] and not app.rendering)
        assert app.start_render(broken, done.append)
        await wait_for(pilot, lambda: "disk full" in notes(app) and not app.rendering)
        assert done == ["slow"]

    run_app(make_ctx(tmp_path), scenario)


def test_render_progress_becomes_notifications(tmp_path):
    async def scenario(app, pilot):
        app.start_render(lambda tools: tools.progress("fetching covers"), lambda _: None)
        await wait_for(pilot, lambda: "fetching covers" in notes(app))

    run_app(make_ctx(tmp_path), scenario)


def test_a_question_from_a_worker_waits_for_the_answer(tmp_path):
    answers = []

    async def scenario(app, pilot):
        app.start_browser(lambda: answers.append(app.ask_from_thread("Posted on @reads?")))
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        assert not app.start_browser(lambda: None)
        assert "a browser is already open — finish there first" in notes(app)
        await pilot.press("y")
        await wait_for(pilot, lambda: answers == [True] and not app.browser_open)

    run_app(make_ctx(tmp_path), scenario)


def test_a_choice_from_a_worker_waits_for_the_answer(tmp_path):
    answers = []
    choices = [("Dark Aria", "Dark Aria"), ("no sound", "")]

    async def scenario(app, pilot):
        app.start_browser(lambda: answers.append(app.choose_from_thread("Sound?", choices)))
        await wait_for(pilot, lambda: isinstance(app.screen, ChoiceModal))
        assert str(app.screen.query_one("Label").render()) == "Sound?"
        await pilot.press("down", "enter")
        await wait_for(pilot, lambda: answers == [""] and not app.browser_open)
        app.start_browser(lambda: answers.append(app.choose_from_thread("Sound?", choices)))
        await wait_for(pilot, lambda: isinstance(app.screen, ChoiceModal))
        await pilot.press("enter")
        await wait_for(pilot, lambda: answers == ["", "Dark Aria"] and not app.browser_open)

    run_app(make_ctx(tmp_path), scenario)


def test_quitting_answers_an_open_choice_none_even_under_another_screen(tmp_path):
    answers = []
    release = threading.Event()
    app_ref = []

    def job():
        try:
            answers.append(app_ref[0].choose_from_thread("Sound?", [("A", "A")]))
            release.wait(5)
        finally:
            release.set()

    async def scenario(app, pilot):
        try:
            app_ref.append(app)
            app.start_browser(job)
            await wait_for(pilot, lambda: isinstance(app.screen, ChoiceModal))
            choice = app.screen
            app.push_screen(TextModal("Something else?"))
            await pilot.pause()
            await pilot.press("ctrl+q")
            await wait_for(pilot, lambda: answers == [None])
            assert choice not in app.screen_stack
            assert app.is_running  # still waiting for the browser
        finally:
            release.set()
        await wait_for(pilot, lambda: not app.is_running)

    run_app(make_ctx(tmp_path), scenario)


def test_a_choice_asked_while_quitting_answers_none_at_once(tmp_path):
    answers = []
    release = threading.Event()
    app_ref = []

    def job():
        try:
            release.wait(5)
            answers.append(app_ref[0].choose_from_thread("Sound?", [("A", "A")]))
        finally:
            release.set()

    async def scenario(app, pilot):
        try:
            app_ref.append(app)
            app.start_browser(job)
            await wait_for(pilot, lambda: app.browser_open)
            await pilot.press("q")
            await pilot.pause()
            assert app.is_running
        finally:
            release.set()
        await wait_for(pilot, lambda: not app.is_running)

    run_app(make_ctx(tmp_path), scenario)
    assert answers == [None]


def test_form_modal_covered_while_saving_stays_open_with_saving_reset(tmp_path):
    """A screen pushed on top of a saving FormModal must not be the one that gets dismissed
    when the save finishes (Screen.dismiss pops the TOP screen)."""
    release = threading.Event()

    def save(values):
        release.wait(5)
        return values["name"]

    async def scenario(app, pilot):
        try:
            form = FormModal("Add", [("name", "Name", "", "")], save)
            app.push_screen(form)
            await pilot.pause()
            form.action_save()
            await wait_for(pilot, lambda: form.saving)
            top = ConfirmModal("Sure?")
            app.push_screen(top)
            await pilot.pause()
            release.set()
            await wait_for(pilot, lambda: not form.saving)
            assert app.screen is top
            assert "saved — close the form with escape" in notes(app)
            await pilot.press("n")
            await pilot.pause()
            assert app.screen is form
        finally:
            release.set()

    run_app(make_ctx(tmp_path), scenario)


def test_quitting_pops_screens_above_the_open_question_first(tmp_path):
    """Quitting while another screen sits on top of the browser's yes/no question must still
    answer it (and not hang), instead of dismissing that other screen by mistake."""
    answers = []
    release = threading.Event()
    app_ref = []

    def job():
        answers.append(app_ref[0].ask_from_thread("Posted?"))
        release.wait(5)

    async def scenario(app, pilot):
        app_ref.append(app)
        app.start_browser(job)
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        question = app.screen
        app.push_screen(TextModal("Something else?"))
        await pilot.pause()
        assert app.screen is not question
        await pilot.press("ctrl+q")  # the modal takes plain keys; ctrl+q always quits
        await wait_for(pilot, lambda: answers == [False])
        assert question not in app.screen_stack
        release.set()
        await wait_for(pilot, lambda: not app.is_running)

    run_app(make_ctx(tmp_path), scenario)


def test_quitting_answers_an_open_question_no_and_waits_for_the_browser(tmp_path):
    answers = []
    release, closed = threading.Event(), threading.Event()

    def job():
        answers.append(app_ref[0].ask_from_thread("Posted?"))
        release.wait(5)  # closing the browser takes a moment
        closed.set()

    app_ref = []

    async def scenario(app, pilot):
        app_ref.append(app)
        app.start_browser(job)
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.press("ctrl+q")  # the modal takes plain keys; ctrl+q always quits
        await wait_for(pilot, lambda: answers == [False])
        await pilot.pause(0.2)
        assert app.is_running  # still closing the browser
        release.set()
        await wait_for(pilot, lambda: not app.is_running)
        assert closed.is_set()

    run_app(make_ctx(tmp_path), scenario)


runner = CliRunner()


def test_tui_command_opens_the_app_with_the_settings(tmp_path, monkeypatch):
    import manhwatok.tui.app as tui_app

    seen = []
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tui_app, "run", lambda settings: seen.append(settings.data_dir))
    result = runner.invoke(cli, ["tui"])
    assert result.exit_code == 0, result.output
    assert seen == [tmp_path]


def test_tui_command_reports_errors(monkeypatch):
    import manhwatok.tui.app as tui_app

    def broken(settings):
        raise ManhwatokError("database is unusable")

    monkeypatch.setattr(tui_app, "run", broken)
    result = runner.invoke(cli, ["tui"])
    assert result.exit_code == 1
    assert "error: database is unusable" in result.output


def test_tui_command_without_the_extra_says_how_to_install(monkeypatch):
    import manhwatok.tui.app as tui_app

    monkeypatch.setattr(tui_app, "run", lambda settings: pytest.fail("the app was opened"))
    monkeypatch.setitem(sys.modules, "textual", None)  # as if the extra weren't installed
    monkeypatch.setitem(sys.modules, "textual.app", None)
    monkeypatch.delitem(sys.modules, "manhwatok.tui.app")
    result = runner.invoke(cli, ["tui"])
    assert result.exit_code == 1
    assert "error: the TUI needs the tui extra — run: uv sync --extra tui" in result.output
