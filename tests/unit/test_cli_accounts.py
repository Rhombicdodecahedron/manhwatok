from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app import container
from manhwatok.cli import app
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import TagInfo
from manhwatok.domain.post import DEFAULT_HASHTAGS
from tests.unit.fakes import FakeMetadata

runner = CliRunner()
GENRES = ["Action", "Drama", "Fantasy", "Romance"]
TAGS = [TagInfo(name=n, category="Theme") for n in ("Harem", "Revenge", "Time Manipulation")]


class Down(FakeMetadata):
    def list_genres(self):
        raise MetadataError("AniList unreachable: boom")

    def list_tags(self):
        raise MetadataError("AniList unreachable: boom")


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        container, "build_metadata", lambda settings: FakeMetadata(tags=TAGS, genres=GENRES)
    )


def _store(tmp_path) -> SqliteStore:
    return SqliteStore(tmp_path / "manhwatok.db")


def _ok(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.output


def _err(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    return result.output


# --- accounts ------------------------------------------------------------------------------


def test_account_add_with_defaults(tmp_path):
    out = _ok(["account", "add", "@Reads"])
    assert out.startswith("added @reads\n@reads\n")
    assert "  genres        any\n" in out
    assert "  repeat days   30\n" in out
    with _store(tmp_path) as store:
        assert store.accounts.get("reads").hashtags == DEFAULT_HASHTAGS


def test_account_add_all_options_in_anilist_spelling(tmp_path):
    _ok(
        [
            "account", "add", "reads",
            "--genres", "action, fantasy",
            "--block-genres", "romance",
            "--block-tags", "harem,time manipulation",
            "--hashtags", "#reads",
            "--accent", "#FF00AA",
            "--cta-title", "Seen *these*?",
            "--cta-follow", "More tomorrow",
            "--repeat-days", "7",
        ]
    )  # fmt: skip
    with _store(tmp_path) as store:
        a = store.accounts.get("reads")
    assert a.genres == ["Action", "Fantasy"]
    assert a.block_genres == ["Romance"]
    assert a.block_tags == ["Harem", "Time Manipulation"]
    assert (a.hashtags, a.accent, a.cta_title, a.cta_follow, a.repeat_days) == (
        "#reads",
        "#ff00aa",
        "Seen *these*?",
        "More tomorrow",
        7,
    )


def test_account_add_existing_fails():
    _ok(["account", "add", "reads"])
    assert "error: account @reads already exists" in _err(["account", "add", "@READS"])


def test_account_add_bad_handle():
    assert "error: 'no spaces' is not a TikTok handle" in _err(["account", "add", "no spaces"])


def test_account_add_bad_accent():
    assert "error: accent must look like #43c9e4" in _err(["account", "add", "ab", "--accent", "x"])


def test_account_add_unknown_genre_suggests_and_saves_nothing(tmp_path):
    out = _err(["account", "add", "reads", "--block-genres", "Romanse"])
    assert "error: unknown genre 'Romanse' — did you mean Romance?" in out
    with _store(tmp_path) as store:
        assert store.accounts.list() == []


def test_account_add_when_anilist_is_down_warns_and_saves(tmp_path, monkeypatch):
    monkeypatch.setattr(container, "build_metadata", lambda settings: Down())
    out = _ok(["account", "add", "reads", "--genres", "Actoin"])
    assert "warning: couldn't check names against AniList" in out
    with _store(tmp_path) as store:
        assert store.accounts.get("reads").genres == ["Actoin"]


def test_account_set_changes_only_given_fields(tmp_path):
    _ok(["account", "add", "reads", "--genres", "Action", "--repeat-days", "7"])
    out = _ok(["account", "set", "@reads", "--hashtags", "#new"])
    assert out.startswith("updated @reads\n")
    with _store(tmp_path) as store:
        a = store.accounts.get("reads")
    assert (a.hashtags, a.genres, a.repeat_days) == ("#new", ["Action"], 7)


def test_account_set_empty_string_clears_a_list(tmp_path):
    _ok(["account", "add", "reads", "--genres", "Action"])
    _ok(["account", "set", "reads", "--genres", ""])
    with _store(tmp_path) as store:
        assert store.accounts.get("reads").genres == []


def test_account_set_without_options_changes_nothing(tmp_path):
    _ok(["account", "add", "reads", "--hashtags", "#old"])
    out = _err(["account", "set", "reads"])
    assert (
        "error: nothing to change — give at least one option "
        "(see `manhwatok account set --help`)" in out
    )
    assert "updated" not in out
    with _store(tmp_path) as store:
        assert store.accounts.get("reads").hashtags == "#old"


def test_account_set_missing_account():
    assert "error: no account @ghost" in _err(["account", "set", "ghost", "--hashtags", "#x"])


def test_account_list_and_show():
    assert "no accounts yet" in _ok(["account", "list"])
    _ok(["account", "add", "bravo.reads"])
    _ok(["account", "add", "alpha", "--genres", "Action,Fantasy", "--block-tags", "Harem"])
    assert _ok(["account", "list"]).splitlines() == [
        "@alpha        Action, Fantasy  blocks Harem  repeat 30d",
        "@bravo.reads  any genre  no blocks  repeat 30d",
    ]
    shown = _ok(["account", "show", "@ALPHA"])
    assert "  block tags    Harem\n" in shown
    assert "  cta follow    Follow for part 2\n" in shown


def test_account_remove_keeps_history(tmp_path):
    _ok(["account", "add", "reads"])
    since = datetime(2026, 9, 1, tzinfo=timezone.utc)
    with _store(tmp_path) as store:
        store.history.record("reads", "20260914-a3f9", [7], since)
    assert "removed @reads (its posting history is kept)" in _ok(["account", "remove", "@reads"])
    assert "error: no account @reads" in _err(["account", "show", "reads"])
    with _store(tmp_path) as store:
        assert store.history.recent("reads", since) == {7}


def test_account_remove_missing():
    assert "error: no account @ghost" in _err(["account", "remove", "ghost"])


# --- themes --------------------------------------------------------------------------------


def test_theme_add_list_show_remove(tmp_path):
    assert "no themes yet" in _ok(["theme", "list"])
    out = _ok(
        ["theme", "add", "Revenge", "-t", "revenge", "-g", "action", "--title", "MC gets *revenge*"]
    )
    assert out.startswith("added theme revenge\n")
    with _store(tmp_path) as store:
        t = store.themes.get("revenge")
    assert (t.tags, t.genres) == (["Revenge"], ["Action"])
    assert _ok(["theme", "list"]).splitlines() == [
        "revenge  MC gets revenge  [Revenge, Action]  score"
    ]
    assert "  min tag rank  60\n" in _ok(["theme", "show", "revenge"])
    assert "removed theme revenge" in _ok(["theme", "remove", "revenge"])
    assert "error: no theme revenge" in _err(["theme", "show", "revenge"])


def test_theme_add_needs_a_tag_or_genre():
    assert "give at least one tag or genre" in _err(["theme", "add", "empty", "--title", "T"])


def test_theme_add_existing_fails():
    _ok(["theme", "add", "revenge", "-t", "Revenge", "--title", "T"])
    assert "error: theme revenge already exists" in _err(
        ["theme", "add", "revenge", "-t", "Revenge", "--title", "T"]
    )


def test_theme_add_unknown_tag():
    out = _err(["theme", "add", "loops", "-t", "Time Manipulaton", "--title", "T"])
    assert "error: unknown tag 'Time Manipulaton' — did you mean Time Manipulation?" in out


def test_theme_add_bad_name():
    assert "is not a theme name" in _err(
        ["theme", "add", "no_way", "-t", "Revenge", "--title", "T"]
    )


def test_help_lists_account_and_theme():
    out = _ok(["--help"])
    assert "account" in out and "theme" in out
