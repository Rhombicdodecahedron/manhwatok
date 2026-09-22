"""Assisted upload: a browser window the user finishes the post in."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from manhwatok.domain.models import Visibility


@dataclass
class UploadReport:
    """What the browser managed to do; `problems` are steps the user has to finish by hand,
    `notes` things it did that the user should know about but needn't act on."""

    attached: bool
    captioned: bool  # the description
    problems: list[str]
    debug_dir: Path | None = None
    titled: bool = False
    sound: str | None = None  # the sound TikTok found and used, as it lists it
    # The time TikTok's own schedule fields now hold, read back from them; None when the post
    # was not scheduled — because none was asked for, or because the browser couldn't set it.
    scheduled_at: datetime | None = None
    # Who TikTok's "Who can see this post" says can see it afterwards, read back from it; None
    # when it was left alone — everyone, TikTok's own default — or when it couldn't be read.
    visibility: Visibility | None = None
    notes: list[str] = field(default_factory=list)


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
        schedule_at: datetime | None = None,
        visibility: Visibility = Visibility.EVERYONE,
    ) -> UploadReport:
        """Open the upload page as `handle`, attach `slides` in order, type `title` and
        `description`, and use the first sound a search for `sound` finds (none if None). With
        `schedule_at`, also switch TikTok to "Schedule" and fill in that date and time (rounded
        to what its picker takes). `visibility` sets "Who can see this post", and is left alone
        for EVERYONE — what TikTok opens on. Then leave the window open for the user to review
        and post — the final button is never clicked here. Raises NotLoggedIn,
        UploadUnavailable, or ManhwatokError if the browser is gone before the slides are
        attached; anything not found later is reported in `problems`."""
        ...

    def close(self) -> None:
        """Close the browser. Never raises; safe to call twice, after the user closed the
        window, or after a Ctrl-C (KeyboardInterrupt) out of login() or upload()."""
        ...
