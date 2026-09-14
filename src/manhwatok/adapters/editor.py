"""Open text in the user's editor ($VISUAL, $EDITOR, else nano/vi) and read it back."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from manhwatok.domain.errors import ManhwatokError


def _editor_command() -> list[str]:
    for var in ("VISUAL", "EDITOR"):
        if cmd := os.environ.get(var, "").strip():
            return shlex.split(cmd)
    for fallback in ("nano", "vi"):
        if shutil.which(fallback):
            return [fallback]
    raise ManhwatokError("no text editor found — set $EDITOR (e.g. export EDITOR=nano)")


def edit_text(text: str, suffix: str = ".txt") -> str | None:
    """Return the edited text, or None if the editor failed or nothing was changed."""
    command = _editor_command()
    fd, name = tempfile.mkstemp(prefix="manhwatok-", suffix=suffix)
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            result = subprocess.run([*command, str(path)])
        except OSError as e:
            raise ManhwatokError(f"could not start editor {command[0]!r}: {e}") from e
        if result.returncode != 0:
            return None
        edited = path.read_text(encoding="utf-8")
        return None if edited == text else edited
    finally:
        path.unlink(missing_ok=True)
