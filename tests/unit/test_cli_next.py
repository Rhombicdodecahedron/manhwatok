import re

import pytest
from typer.testing import CliRunner

from manhwatok.adapters.fs_posts import FsPostRepository
from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app import container
from manhwatok.app.post_tools import PostTools
from manhwatok.cli import app
from manhwatok.domain.account import Account
from manhwatok.domain.models import ArtSourceName
from manhwatok.domain.theme import Theme
from manhwatok.ports.art import ArtOption
from manhwatok.ports.chapters import ChapterInfo
from tests.unit.fakes import (
    FakeArtSource,
    FakeChapterPages,
    FakeChapters,
    FakeCovers,
    FakeCutter,
    FakeMetadata,
    FakeRenderer,
    manhwa,
)

runner = CliRunner()
BOXER = manhwa(anilist_id=119174, title="The Boxer")
PICKS = [manhwa(anilist_id=i, title=f"Title {i}", description=f"Hook {i}.") for i in (11, 22)]
CH12 = ChapterInfo("ch-12", "12", "Talent", "en", 36)


class Catalogue(FakeMetadata):
    """AniList: finds BOXER by name, and answers every search with the picks."""

    def search(self, query):
        self.queries.append(query)
        return list(PICKS)


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def wire(tmp_path, monkeypatch):
    """Fake network and renderer behind the real context; real database and post folders.
    Returns (post folders, the pins source)."""
    from manhwatok.app.chapter_post import ChapterTools

    repo = FsPostRepository(tmp_path / "data" / "posts")
    pages = FakeChapterPages(chapters=[CH12])
    pages.root = tmp_path
    pins = FakeArtSource({11: [ArtOption("pin", "https://x.test/11.jpg")]})
    monkeypatch.setattr(container, "build_metadata", lambda settings: Catalogue([BOXER, *PICKS]))
    monkeypatch.setattr(
        container, "build_chapter_source", lambda settings, cache: FakeChapters({})
    )
    monkeypatch.setattr(
        container,
        "build_art_sources",
        lambda settings, cache: {
            name: pins if name is ArtSourceName.PINS else FakeArtSource()
            for name in ArtSourceName
        },
    )
    monkeypatch.setattr(
        container,
        "build_chapter_tools",
        lambda settings, store: ChapterTools(
            pages=pages,
            cutter=FakeCutter(4),
            chapters=store.chapters,
            pages_dir=tmp_path / "pages",
            sources={},
        ),
    )
    monkeypatch.setattr(
        container,
        "build_post_tools",
        lambda settings, editor, progress, metadata=None, scenes=None: PostTools(
            repo,
            FakeCovers({11: tmp_path / "11.jpg", 22: tmp_path / "22.jpg"}),
            FakeRenderer(),
            editor,
            progress,
        ),
    )
    return repo, pins


def _account(tmp_path, rotation, **fields):
    with SqliteStore(tmp_path / "data" / "manhwatok.db") as store:
        store.themes.add(Theme(name="isekai", tags=["Isekai"], title="Isekai *picks*"))
        store.accounts.add(Account(handle="reads", rotation=rotation, **fields))


def _cursor(tmp_path) -> int:
    with SqliteStore(tmp_path / "data" / "manhwatok.db") as store:
        return store.accounts.get("reads").rotation_cursor


def _ids(output: str) -> list[str]:
    return re.findall(r"post (\d{8}-[0-9a-f]{4})", output)


def test_next_makes_the_rotations_posts_and_says_how_to_review_them(tmp_path, wire):
    repo, pins = wire
    _account(tmp_path, ["chapter:The Boxer", "theme:isekai"], art_source="pins")

    result = runner.invoke(app, ["next", "-a", "@reads", "--count", "2"])

    assert result.exit_code == 0, result.output
    chapter_id, list_id = _ids(result.output)
    assert repo.get(chapter_id).chapter.number == "12"
    assert repo.get(list_id).theme == "isekai"
    assert f"post {chapter_id} · The Boxer chapter 12 part 1/1 · 6 slides" in result.output
    assert f"post {list_id} · Isekai picks · 4 slides" in result.output
    assert "manhwatok tui" in result.output and "manhwatok render <id>" in result.output
    assert pins.fetched == ["https://x.test/11.jpg"]  # the account's art source
    assert _cursor(tmp_path) == 0


def test_next_makes_one_post_by_default(tmp_path, wire):
    _account(tmp_path, ["theme:isekai", "chapter:The Boxer"])

    result = runner.invoke(app, ["next", "-a", "reads"])

    assert result.exit_code == 0, result.output
    assert len(_ids(result.output)) == 1
    assert _cursor(tmp_path) == 1


def test_next_warns_about_a_chapter_with_nothing_left_and_moves_on(tmp_path, wire):
    _account(tmp_path, ["chapter:The Boxer", "theme:isekai"])
    runner.invoke(app, ["next", "-a", "reads"])

    result = runner.invoke(app, ["next", "-a", "reads", "--count", "2"])

    assert result.exit_code == 0, result.output
    assert "The Boxer: every listed chapter is built" in result.output
    assert len(_ids(result.output)) == 2


def test_next_keeps_what_it_made_before_a_failure(tmp_path, wire):
    repo, _ = wire
    _account(tmp_path, ["chapter:The Boxer"])

    result = runner.invoke(app, ["next", "-a", "reads", "--count", "2"])

    assert result.exit_code == 1, result.output
    [made] = _ids(result.output)
    assert repo.get(made).chapter.number == "12"
    assert "error: nothing left to post in @reads's rotation" in result.output


def test_next_without_a_rotation_says_how_to_set_one(tmp_path, wire):
    _account(tmp_path, [])

    result = runner.invoke(app, ["next", "-a", "reads"])

    assert result.exit_code == 1
    assert "--rotation" in result.output


def test_next_for_an_unknown_account_fails_cleanly(tmp_path, wire):
    result = runner.invoke(app, ["next", "-a", "nobody"])

    assert result.exit_code == 1
    assert "error:" in result.output
