import pytest
from typer.testing import CliRunner

from manhwatok.app import container
from manhwatok.cli import app
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Status, TagInfo
from tests.unit.fakes import FakeChapters, FakeMetadata, manhwa

runner = CliRunner()


def test_help_runs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "TikTok" in result.output


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path))


def _wire(monkeypatch, metadata, chapters=None):
    monkeypatch.setattr(container, "build_metadata", lambda settings: metadata)
    monkeypatch.setattr(
        container, "build_chapter_source", lambda settings: chapters or FakeChapters({})
    )


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert "suggest" in result.output
    assert "tags" in result.output


def test_suggest_prints_ranked_titles_with_chapter_labels(monkeypatch):
    meta = FakeMetadata(
        [
            manhwa(anilist_id=1, title="Marry My Husband", status=Status.FINISHED, chapters=150,
                   score=82, genres=["Drama", "Romance"]),
            manhwa(anilist_id=2, title="Doom Breaker", status=Status.HIATUS, score=78,
                   genres=["Action"]),
        ]
    )
    _wire(monkeypatch, meta, FakeChapters({2: 101}))
    result = runner.invoke(app, ["suggest", "-t", "Time Manipulation", "-t", "Revenge", "-n", "5"])
    assert result.exit_code == 0, result.output
    assert " 1. Marry My Husband  [150 chapters · completed]  82%" in result.output
    assert "    Drama, Romance" in result.output
    assert " 2. Doom Breaker  [hiatus · ch. 101]  78%" in result.output
    [q] = meta.queries
    assert q.tags == ["Time Manipulation", "Revenge"]
    assert q.limit == 5


def test_suggest_no_chapters_skips_mangaupdates(monkeypatch):
    _wire(monkeypatch, FakeMetadata([manhwa()]))

    def boom(settings):
        raise AssertionError("chapter source must not be built")

    monkeypatch.setattr(container, "build_chapter_source", boom)
    result = runner.invoke(app, ["suggest", "-g", "Action", "--no-chapters"])
    assert result.exit_code == 0, result.output
    assert " 1. Test Manhwa  [ongoing]  –" in result.output


def test_suggest_requires_a_filter():
    result = runner.invoke(app, ["suggest"])
    assert result.exit_code == 1
    assert "at least one --tag or --genre" in result.output


def test_suggest_reports_metadata_errors(monkeypatch):
    class Down(FakeMetadata):
        def search(self, query):
            raise MetadataError("AniList rate limit hit — retry in 30s")

    _wire(monkeypatch, Down())
    result = runner.invoke(app, ["suggest", "-t", "Revenge"])
    assert result.exit_code == 1
    assert "error: AniList rate limit hit" in result.output


def test_suggest_no_matches_hint(monkeypatch):
    _wire(monkeypatch, FakeMetadata([]))
    result = runner.invoke(app, ["suggest", "-t", "Revenge"])
    assert result.exit_code == 0
    assert "no matches" in result.output


def test_tags_grouped_by_category_and_filtered(monkeypatch):
    _wire(
        monkeypatch,
        FakeMetadata(
            tags=[
                TagInfo(name="Tragedy", category="Theme-Drama", description="Sad."),
                TagInfo(name="Time Manipulation", category="Theme-Sci-Fi", description="Loops."),
                TagInfo(name="Revenge", category="Theme-Drama", description="Revenge plot."),
            ]
        ),
    )
    result = runner.invoke(app, ["tags", "time"])
    assert result.exit_code == 0, result.output
    assert "Theme-Sci-Fi\n  Time Manipulation\n" in result.output
    assert "Revenge" not in result.output

    result = runner.invoke(app, ["tags", "--category", "theme-drama"])
    assert "Theme-Drama\n  Revenge\n  Tragedy\n" in result.output
