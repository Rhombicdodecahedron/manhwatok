from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    if env := os.environ.get("MANHWATOK_DATA_DIR"):
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME", "~/.local/share")
    return Path(xdg).expanduser() / "manhwatok"


def _default_export_dir() -> Path:
    if env := os.environ.get("MANHWATOK_EXPORT_DIR"):
        return Path(env).expanduser()
    downloads = Path("~/Downloads").expanduser()
    return (downloads if downloads.is_dir() else Path.cwd()) / "manhwatok"


@dataclass
class Settings:
    data_dir: Path = field(default_factory=_default_data_dir)
    http_timeout: float = 20.0
    chapter_cache_hours: float = 24.0
    export_dir: Path = field(default_factory=_default_export_dir)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "manhwatok.db"

    @property
    def posts_dir(self) -> Path:
        return self.data_dir / "posts"

    @property
    def covers_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def browser_dir(self) -> Path:
        """One persistent Chromium profile (TikTok login) per account handle."""
        return self.data_dir / "browser"

    @property
    def debug_dir(self) -> Path:
        """Screenshots and page HTML saved by `upload --debug`."""
        return self.data_dir / "debug"
