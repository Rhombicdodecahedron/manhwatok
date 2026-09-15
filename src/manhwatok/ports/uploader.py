"""Assisted upload: a browser window the user finishes the post in."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class UploadReport:
    """What the browser managed to do; `problems` are steps the user has to finish by hand."""

    attached: bool
    captioned: bool
    problems: list[str]
    debug_dir: Path | None = None


class Uploader(Protocol):
    def login(self, handle: str) -> None:
        """Open the account's browser profile on the login page; return once the user closed
        the window."""
        ...

    def upload(self, handle: str, slides: list[Path], caption: str, debug: bool) -> UploadReport:
        """Open the upload page as `handle`, attach `slides` in order and type `caption`, then
        leave the window open for the user to review and post. Raises NotLoggedIn,
        UploadUnavailable, or ManhwatokError if the browser is gone before the slides are
        attached; anything not found later is reported in `problems`."""
        ...

    def close(self) -> None:
        """Close the browser. Never raises; safe to call twice, after the user closed the
        window, or after a Ctrl-C (KeyboardInterrupt) out of login() or upload()."""
        ...
