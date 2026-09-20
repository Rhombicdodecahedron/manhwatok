from pathlib import Path

import pytest
from typer.testing import CliRunner

from manhwatok.app import container
from manhwatok.cli import app
from manhwatok.domain.errors import MetadataError
from manhwatok.ports.chapters import ChapterInfo
from tests.unit.fakes import (
    FakeChapterPages,
    FakeCutter,
    FakeMetadata,
    manhwa,
    post,
)

runner = CliRunner()
BOXER = manhwa(anilist_id=119174, title="The Boxer")
CH12 = ChapterInfo("ch-12", "12", "Talent", "en", 36)
CH13 = ChapterInfo("ch-13", "13", "", "en", 37)


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MANHWATOK_EXPORT_DIR", str(tmp_path / "exports"))


@pytest.fixture
def wire(tmp_path, monkeypatch):
    """Scripted AniList and MangaDex, real post folders and a real database."""

    def _wire(chapters=(CH12, CH13), panels=4, error=None, results=(BOXER,)):
        from manhwatok.app.chapter_post import ChapterTools

        pages = FakeChapterPages(chapters=list(chapters), error=error)
        pages.root = tmp_path
        cutter = FakeCutter(panels)
        monkeypatch.setattr(
            container, "build_metadata", lambda settings: FakeMetadata(list(results))
        )
        monkeypatch.setattr(
            container,
            "build_chapter_tools",
            lambda settings, store: ChapterTools(
                pages=pages,
                cutter=cutter,
                chapters=store.chapters,
                pages_dir=tmp_path / "pages",
            ),
        )
        return pages, cutter

    return _wire


def _ok(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.output


def _err(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    return result.output


def test_chapter_list_shows_each_chapters_pages_and_state(wire):
    wire()
    out = _ok(["chapter", "list", "The Boxer"])
    assert "12" in out and "36 pages" in out
    assert "13" in out


def test_chapter_list_says_so_when_mangadex_has_no_english_chapters(wire):
    wire(chapters=())
    assert "no English chapters" in _err(["chapter", "list", "The Boxer"])


def test_chapter_list_reports_a_source_failure(wire):
    wire(error=MetadataError("MangaDex is down"))
    assert "MangaDex is down" in _err(["chapter", "list", "The Boxer"])


def test_chapter_next_names_the_chapter_and_part_without_building(wire):
    pages, cutter = wire()
    out = _ok(["chapter", "next", "The Boxer"])
    assert "chapter 12" in out and "part 1" in out
    assert pages.downloads == [] and cutter.cuts == []


def test_chapter_build_prints_the_post_id_the_chapter_and_the_part(wire):
    wire(panels=40)
    out = _ok(["chapter", "build", "The Boxer"])
    assert "chapter 12" in out and "part 1/2" in out and "slides" in out
    assert "export with: manhwatok export" in out


def test_chapter_build_continues_without_a_number(wire):
    wire(panels=40)
    _ok(["chapter", "build", "The Boxer"])
    assert "part 2/2" in _ok(["chapter", "build", "The Boxer"])


def test_chapter_build_takes_an_explicit_chapter_and_part(wire):
    wire(panels=40)
    out = _ok(["chapter", "build", "The Boxer", "--number", "13", "--part", "2"])
    assert "chapter 13" in out and "part 2/2" in out


def test_chapter_build_records_the_account(wire):
    from manhwatok.adapters.fs_posts import FsPostRepository

    wire()
    _ok(["account", "add", "@reads"])
    out = _ok(["chapter", "build", "The Boxer", "--account", "@reads"])
    post_id = out.split("post ")[1].split(" ")[0]
    import os

    repo = FsPostRepository(Path(os.environ["MANHWATOK_DATA_DIR"]) / "posts")
    assert repo.get(post_id).account == "reads"


def test_chapter_build_reports_a_metadata_failure_as_an_error(wire):
    wire(error=MetadataError("MangaDex is down"))
    assert "MangaDex is down" in _err(["chapter", "build", "The Boxer"])


def test_chapter_commands_accept_an_anilist_id_as_well_as_a_title(wire):
    wire()
    _ok(["chapter", "list", "The Boxer"])  # so the id is known
    assert "12" in _ok(["chapter", "list", "119174"])


def test_chapter_list_after_building_shows_what_was_built(wire):
    wire(panels=40)
    _ok(["chapter", "build", "The Boxer"])
    out = _ok(["chapter", "list", "The Boxer"])
    assert "1/2 parts" in out


def test_a_chapter_post_shows_up_in_posts(wire):
    wire()
    _ok(["chapter", "build", "The Boxer"])
    assert "The Boxer Chapter 12" in _ok(["posts"])


def test_editing_a_chapter_posts_picks_is_refused(wire):
    wire()
    out = _ok(["chapter", "build", "The Boxer"])
    post_id = out.split("post ")[1].split(" ")[0]
    assert "chapter post" in _err(["edit", post_id])


def test_choosing_a_cover_for_a_chapter_post_is_refused(wire):
    wire()
    out = _ok(["chapter", "build", "The Boxer"])
    post_id = out.split("post ")[1].split(" ")[0]
    assert "chapter post" in _err(["cover", post_id, "quad"])


def test_deleting_a_chapter_post_lets_it_be_built_again(wire):
    wire()
    first = _ok(["chapter", "build", "The Boxer"])
    post_id = first.split("post ")[1].split(" ")[0]
    _ok(["delete", post_id, "--yes"])
    assert "chapter 12" in _ok(["chapter", "build", "The Boxer"])


def test_the_chapter_help_says_the_posting_is_the_users_own_call():
    out = _ok(["chapter", "--help"])
    assert "copyright" in out.lower() or "rights" in out.lower()


def test_chapter_list_warns_when_the_run_starts_late(wire):
    pages, _ = wire()
    pages.elsewhere = {"es": 11, "it": 9}
    out = _ok(["chapter", "list", "The Boxer"])
    assert "English starts at chapter 12" in out
    assert "Spanish (11)" in out


def _wire_both(monkeypatch, tmp_path, mangadex=(CH12, CH13), webtoons=(), panels=4):
    """Both sources scripted, so --source and the fallback can be exercised."""
    from manhwatok.app.chapter_post import ChapterTools
    from manhwatok.domain.models import ChapterSourceName

    md = FakeChapterPages(chapters=list(mangadex))
    wt = FakeChapterPages(chapters=list(webtoons))
    md.root = wt.root = tmp_path
    cutter = FakeCutter(panels)
    monkeypatch.setattr(container, "build_metadata", lambda settings: FakeMetadata([BOXER]))
    monkeypatch.setattr(
        container,
        "build_chapter_tools",
        lambda settings, store: ChapterTools(
            pages=md,
            cutter=cutter,
            chapters=store.chapters,
            pages_dir=tmp_path / "pages",
            sources={ChapterSourceName.MANGADEX: md, ChapterSourceName.WEBTOONS: wt},
        ),
    )
    return md, wt


def test_chapter_list_falls_back_to_webtoons_when_mangadex_has_nothing(monkeypatch, tmp_path):
    _wire_both(monkeypatch, tmp_path, mangadex=(), webtoons=(CH12,))
    out = _ok(["chapter", "list", "The Boxer"])
    assert "webtoons" in out
    assert "mangadex has nothing, using webtoons" in out


def test_chapter_list_takes_the_source_it_is_given(monkeypatch, tmp_path):
    _wire_both(monkeypatch, tmp_path, mangadex=(CH12, CH13), webtoons=(CH12,))
    out = _ok(["chapter", "list", "The Boxer", "--source", "webtoons"])
    assert "webtoons" in out and "ch. 13" not in out


def test_a_title_keeps_the_source_it_was_built_from(monkeypatch, tmp_path):
    _wire_both(monkeypatch, tmp_path, mangadex=(CH12, CH13), webtoons=(CH12,))
    built = _ok(["chapter", "build", "The Boxer", "--source", "webtoons"])
    assert "webtoons chapter 12" in built
    assert "webtoons" in _ok(["chapter", "list", "The Boxer"])


def test_an_unknown_source_is_refused():
    result = runner.invoke(app, ["chapter", "list", "The Boxer", "--source", "asura"])
    assert result.exit_code == 2
