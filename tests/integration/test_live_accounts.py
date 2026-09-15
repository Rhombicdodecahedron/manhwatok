"""An account's block list and repeat history against live AniList, through the real CLI.

Run with: MANHWATOK_LIVE=1 uv run pytest tests/integration/test_live_accounts.py -s
"""

import os
import re
import shlex
import sys

import pytest
from typer.testing import CliRunner

from manhwatok.adapters.anilist import AniListSource
from manhwatok.adapters.fs_posts import FsPostRepository
from manhwatok.cli import app
from manhwatok.domain.theme import Theme

pytestmark = pytest.mark.skipif(
    os.environ.get("MANHWATOK_LIVE") != "1", reason="set MANHWATOK_LIVE=1 to hit real APIs"
)
runner = CliRunner()
THEME = Theme(name="revenge-drama", tags=["Revenge"], genres=["Drama"], title="Revenge *dramas*")


def _run(args: list[str]) -> str:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.output


def _built_id(output: str) -> str:
    return re.search(r"post (\d{8}-[0-9a-f]{4})", output).group(1)


def test_blocked_genre_and_repeat_window(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MANHWATOK_EXPORT_DIR", str(tmp_path / "exports"))
    # "editor" that accepts the prefilled draft unchanged
    monkeypatch.setenv("VISUAL", f"{shlex.quote(sys.executable)} -c pass")

    # Without the block, this theme's top titles include Romance ones, so the check means something.
    unblocked = AniListSource().search(THEME.to_query(12))
    assert any("Romance" in m.genres for m in unblocked)

    _run(["account", "add", "@manhwatok.live", "--block-genres", "romance"])  # AniList spelling
    _run(["theme", "add", THEME.name, "-t", "Revenge", "-g", "drama", "--title", THEME.title])
    first = _built_id(
        _run(["build", "-a", "manhwatok.live", "--theme", THEME.name, "-n", "6", "--no-chapters"])
    )
    posts = FsPostRepository(tmp_path / "posts")
    post = posts.get(first)
    assert post.account == "manhwatok.live"
    assert len(post.items) == 6
    assert not [m.title for m in post.candidates if "Romance" in m.genres]

    _run(["export", first])
    second = _built_id(
        _run(["build", "-a", "manhwatok.live", "--theme", THEME.name, "-n", "6", "--no-chapters"])
    )
    first_ids = {i.manhwa.anilist_id for i in post.items}
    second_ids = {i.manhwa.anilist_id for i in posts.get(second).items}
    assert len(second_ids) == 6
    assert first_ids.isdisjoint(second_ids)
    print(f"\nrendered posts → {posts.folder(first)} and {posts.folder(second)}")
