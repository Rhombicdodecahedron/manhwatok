import re

import pytest
from typer.testing import CliRunner

from manhwatok.adapters.fs_posts import FsPostRepository
from manhwatok.app import container
from manhwatok.app.post_tools import PostTools
from manhwatok.cli import app
from tests.unit.fakes import (
    FakeChapters,
    FakeCovers,
    FakeMetadata,
    FakeRenderer,
    ScriptedEditor,
    manhwa,
    post,
)

runner = CliRunner()
CANDIDATES = [
    manhwa(anilist_id=11, title="Doom Breaker", description="Sent back ten years. More."),
    manhwa(anilist_id=22, title="Kubera", description="Gods. More."),
]


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MANHWATOK_EXPORT_DIR", str(tmp_path / "exports"))


@pytest.fixture
def wire(tmp_path, monkeypatch):
    """Fake network, editor and renderer; real post folders under tmp_path."""

    def _wire(respond=lambda text: text + "\n", results=CANDIDATES):
        editor = ScriptedEditor(respond)
        repo = FsPostRepository(tmp_path / "data" / "posts")
        monkeypatch.setattr(container, "build_metadata", lambda settings: FakeMetadata(results))
        monkeypatch.setattr(container, "build_chapter_source", lambda settings: FakeChapters({}))
        monkeypatch.setattr(
            container,
            "build_post_tools",
            lambda settings, _editor, progress: PostTools(
                repo,
                FakeCovers({11: tmp_path / "11.jpg", 22: tmp_path / "22.jpg"}),
                FakeRenderer(),
                editor,
                progress,
            ),
        )
        return repo, editor

    return _wire


def _post_id(output: str) -> str:
    return re.search(r"post (\d{8}-[0-9a-f]{4})", output).group(1)


def test_build_renders_and_prints_next_step(wire):
    repo, editor = wire()
    result = runner.invoke(
        app, ["build", "-t", "Revenge", "--title", "MC *regresses*", "--no-chapters"]
    )
    assert result.exit_code == 0, result.output
    post_id = _post_id(result.output)
    assert "· 4 slides →" in result.output
    assert f"export with: manhwatok export {post_id}" in result.output
    assert repo.get(post_id).title == "MC *regresses*"
    assert "title: MC *regresses*" in editor.shown[0]


def test_build_requires_a_filter(wire):
    wire()
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 1
    assert "at least one --tag or --genre" in result.output


def test_build_cancelled(wire):
    repo, _ = wire(respond=lambda text: None)
    result = runner.invoke(app, ["build", "-t", "Revenge"])
    assert result.exit_code == 0
    assert "cancelled — nothing saved" in result.output
    assert repo.list() == []


def test_build_bad_draft_exits_1_with_edit_hint(wire):
    wire(respond=lambda text: "title: T\n")
    result = runner.invoke(app, ["build", "-t", "Revenge"])
    assert result.exit_code == 1
    assert "error: no titles left" in result.output
    assert "fix with: manhwatok edit" in result.output


def test_build_bad_accent(wire):
    wire()
    result = runner.invoke(app, ["build", "-t", "Revenge", "--accent", "cyan"])
    assert result.exit_code == 1
    assert "accent must look like #43c9e4" in result.output


def test_edit_render_export_posts_flow(wire, tmp_path):
    repo, _ = wire(respond=lambda text: text.replace("Hook 1", "New hook"))
    repo.save(post())

    result = runner.invoke(app, ["edit", "20260914-a3f9"])
    assert result.exit_code == 0, result.output
    assert "post 20260914-a3f9 · 5 slides →" in result.output
    assert repo.get("20260914-a3f9").items[0].hook == "New hook"

    result = runner.invoke(app, ["render", "20260914-a3f9"])
    assert result.exit_code == 0, result.output
    assert "5 slides" in result.output

    result = runner.invoke(app, ["export", "20260914-a3f9"])
    assert result.exit_code == 0, result.output
    assert f"exported → {tmp_path / 'exports' / '20260914-a3f9'}" in result.output
    assert (tmp_path / "exports" / "20260914-a3f9" / "caption.txt").is_file()

    result = runner.invoke(app, ["export", "20260914-a3f9", "--out", str(tmp_path / "elsewhere")])
    assert result.exit_code == 0
    assert (tmp_path / "elsewhere" / "20260914-a3f9" / "05.png").is_file()


def test_edit_no_changes(wire):
    repo, _ = wire(respond=lambda text: None)
    repo.save(post())
    result = runner.invoke(app, ["edit", "20260914-a3f9"])
    assert result.exit_code == 0
    assert "no changes" in result.output


@pytest.mark.parametrize("command", ["edit", "render", "export"])
def test_unknown_post(wire, command):
    wire()
    result = runner.invoke(app, [command, "20260914-ffff"])
    assert result.exit_code == 1
    assert "error: no post 20260914-ffff" in result.output


def test_export_before_render(wire):
    repo, _ = wire()
    repo.save(post())
    result = runner.invoke(app, ["export", "20260914-a3f9"])
    assert result.exit_code == 1
    assert "run: manhwatok render 20260914-a3f9" in result.output


def test_export_destination_blocked_by_a_file_exits_1(wire, tmp_path):
    wire()
    built = runner.invoke(
        app, ["build", "-t", "Revenge", "--title", "MC *regresses*", "--no-chapters"]
    )
    post_id = _post_id(built.output)
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"not a directory")
    result = runner.invoke(app, ["export", post_id, "--out", str(blocker)])
    assert result.exit_code == 1
    assert result.output.startswith("error: ")


def test_posts_lists_newest_first_and_marks_drafts(wire):
    from datetime import datetime, timezone

    repo, _ = wire()
    repo.save(post(id="20260913-0001", created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    repo.save(
        post(
            id="20260914-0002",
            title="",
            items=[],
            created_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )
    )
    result = runner.invoke(app, ["posts"])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert lines[0].startswith("20260914-0002") and "draft" in lines[0] and "(untitled)" in lines[0]
    assert lines[1].startswith("20260913-0001") and "5 slides" in lines[1]
    assert "Manhwa where the MC regresses" in lines[1]


def test_posts_empty(wire):
    wire()
    result = runner.invoke(app, ["posts"])
    assert "no posts yet" in result.output


def test_help_lists_post_commands():
    result = runner.invoke(app, ["--help"])
    for command in ("build", "edit", "render", "export", "posts"):
        assert command in result.output
