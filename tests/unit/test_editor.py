import os
import shlex
import sys

import pytest

from manhwatok.adapters.editor import edit_text
from manhwatok.domain.errors import ManhwatokError


def _editor(monkeypatch, tmp_path, script: str):
    """Point $EDITOR at a tiny Python script that receives the file path as argv[1]."""
    path = tmp_path / "fake_editor.py"
    path.write_text(script)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", f"{shlex.quote(sys.executable)} {shlex.quote(str(path))}")


def test_returns_edited_text(monkeypatch, tmp_path):
    _editor(monkeypatch, tmp_path, "import sys\nopen(sys.argv[1], 'a').write('added\\n')\n")
    assert edit_text("hello\n") == "hello\nadded\n"


def test_unchanged_text_means_none(monkeypatch, tmp_path):
    _editor(monkeypatch, tmp_path, "pass\n")
    assert edit_text("hello\n") is None


def test_editor_failure_means_none(monkeypatch, tmp_path):
    _editor(monkeypatch, tmp_path, "import sys\nopen(sys.argv[1], 'a').write('x')\nsys.exit(1)\n")
    assert edit_text("hello\n") is None


def test_visual_wins_over_editor(monkeypatch, tmp_path):
    _editor(monkeypatch, tmp_path, "pass\n")
    script = tmp_path / "visual.py"
    script.write_text("import sys\nopen(sys.argv[1], 'w').write('from visual')\n")
    monkeypatch.setenv("VISUAL", f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}")
    assert edit_text("hello") == "from visual"


def test_temp_file_is_removed(monkeypatch, tmp_path):
    _editor(monkeypatch, tmp_path, "import sys\nopen('seen.txt', 'w').write(sys.argv[1])\n")
    monkeypatch.chdir(tmp_path)
    edit_text("hello")
    seen = (tmp_path / "seen.txt").read_text()
    assert seen.endswith(".txt")
    assert not os.path.exists(seen)


def test_missing_editor_binary(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "definitely-not-an-editor-xyz")
    with pytest.raises(ManhwatokError, match="could not start editor"):
        edit_text("hello")


def test_no_editor_configured_or_installed(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr("manhwatok.adapters.editor.shutil.which", lambda name: None)
    with pytest.raises(ManhwatokError, match="set \\$EDITOR"):
        edit_text("hello")
