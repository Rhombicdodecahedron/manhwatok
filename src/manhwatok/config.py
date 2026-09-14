from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    if env := os.environ.get("MANHWATOK_DATA_DIR"):
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME", "~/.local/share")
    return Path(xdg).expanduser() / "manhwatok"


@dataclass
class Settings:
    data_dir: Path = field(default_factory=_default_data_dir)
    http_timeout: float = 20.0
    chapter_cache_hours: float = 24.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "manhwatok.db"
