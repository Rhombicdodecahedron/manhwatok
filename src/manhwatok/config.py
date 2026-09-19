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


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


@dataclass
class Settings:
    data_dir: Path = field(default_factory=_default_data_dir)
    http_timeout: float = 20.0
    chapter_cache_hours: float = 24.0
    # An AniList-to-MangaDex pairing does not change once made, so it is kept far longer.
    art_cache_days: float = 30.0
    export_dir: Path = field(default_factory=_default_export_dir)
    # An app Reddit has approved for you; without one the reddit art source says how to get it.
    reddit_client_id: str = field(default_factory=lambda: _env("MANHWATOK_REDDIT_CLIENT_ID"))
    reddit_client_secret: str = field(
        default_factory=lambda: _env("MANHWATOK_REDDIT_CLIENT_SECRET")
    )
    reddit_user: str = field(default_factory=lambda: _env("MANHWATOK_REDDIT_USER"))

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
