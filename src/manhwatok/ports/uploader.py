"""Assisted upload: a browser window the user finishes the post in."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class UploadReport:
    """What the browser managed to do; `problems` are steps the user has to finish by hand."""

    attached: bool
    captioned: bool  # the description
    problems: list[str]
    debug_dir: Path | None = None
    titled: bool = False
    sound: str | None = None  # the sound TikTok found and used, as it lists it


class Uploader(Protocol):
    def login(self, handle: str) -> None:
        """Open the account's browser profile on the login page; return once the user quit
        the browser."""
        ...

    def upload(
        self,
        handle: str,
        slides: list[Path],
        title: str,
        description: str,
        sound: str | None,
        debug: bool,
    ) -> UploadReport:
        """Open the upload page as `handle`, attach `slides` in order, type `title` and
        `description`, and use the first sound a search for `sound` finds (none if None), then
        leave the window open for the user to review and post. Raises NotLoggedIn,
        UploadUnavailable, or ManhwatokError if the browser is gone before the slides are
        attached; anything not found later is reported in `problems`."""
        ...

    def close(self) -> None:
        """Close the browser. Never raises; safe to call twice, after the user closed the
        window, or after a Ctrl-C (KeyboardInterrupt) out of login() or upload()."""
        ...
