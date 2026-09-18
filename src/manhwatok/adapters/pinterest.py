"""Pictures from a Pinterest search, by way of gallery-dl.

Results keep Pinterest's own ranking, which is what responds to the words searched for — asking
for "epic fight scene" rather than just the title returns a genuinely different, more
slide-shaped set. Sorting them any other way discards that.

Pinterest has no public search API — the v5 one reaches only your own boards — so this shells
out to gallery-dl rather than putting scraping code in manhwatok. When Pinterest changes its
internals, that is gallery-dl's to patch.

Two things to know about what comes back. Pinterest records no origin for a pin: `source_link`
is empty and the domain reads "Uploaded by user" on essentially everything, so unlike Danbooru
there is no artist to credit and none is shown. And a search is a text match over pin captions,
with no id to pair a title on, so a title whose name is an ordinary phrase will collect whatever
else shares it. Look at what you pick.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus

from manhwatok.adapters.picture_download import download_picture
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Manhwa
from manhwatok.ports.art import ArtOption

SEARCH = "https://www.pinterest.com/search/pins/?q="
LIMIT = 30
MIN_SIDE = 600  # a slide is 1080x1920; Pinterest also serves 236px thumbnails
HINT = "pinterest art needs gallery-dl: uv sync --extra pinterest"

# Runs gallery-dl with these arguments and returns its stdout.
RunFn = Callable[[list[str]], str]


def _gallery_dl(argv: list[str]) -> str:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    if done.returncode != 0:
        detail = (done.stderr or "").strip().splitlines()
        raise ManhwatokError(f"pinterest search failed: {detail[-1] if detail else 'no output'}")
    return done.stdout


class PinterestSource:
    def __init__(
        self,
        run: RunFn | None = None,
        limit: int = LIMIT,
        min_side: int = MIN_SIDE,
    ) -> None:
        self._run = run or _gallery_dl
        self._limit = limit
        self._min_side = min_side

    def close(self) -> None:
        """Nothing to close: each search is its own process."""

    def options(self, manhwa: Manhwa, tag: str | None = None) -> list[ArtOption]:
        terms = " ".join(part for part in (manhwa.title, "manhwa", tag or "") if part).strip()
        url = SEARCH + quote_plus(terms)
        argv = ["gallery-dl", "-j", "--range", f"1-{self._limit}", url]
        try:
            out = self._run(argv)
        except FileNotFoundError as e:
            raise ManhwatokError(HINT) from e
        except subprocess.SubprocessError as e:
            raise ManhwatokError(f"pinterest search failed: {e}") from e

        # Keyed by url: a Pinterest search lists each pin more than once, and the mapping is
        # what collapses those to one.
        found: dict[str, tuple[int, int]] = {}
        for width, height, link in _pins(out):
            if min(width, height) < self._min_side:
                continue
            found.setdefault(link, (width, height))
        # Left in Pinterest's own order: that ranking is the only thing here that knows what
        # the search meant. Re-arranging is the caller's choice (ArtOrder).
        return [
            ArtOption(label=f"{w}x{h}  (no artist recorded)", url=link, width=w, height=h)
            for link, (w, h) in found.items()
        ]

    def fetch(self, option: ArtOption, into: Path) -> Path:
        return download_picture(option.url, into)


def _pins(out: str):
    """The (width, height, url) of every pin in gallery-dl's JSON dump, dupes and all."""
    try:
        entries = json.loads(out or "[]")
    except ValueError as e:
        raise ManhwatokError(f"could not read the pinterest search: {e}") from e
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not (isinstance(entry, list) and entry and isinstance(entry[-1], dict)):
            continue
        orig = ((entry[-1].get("images") or {}).get("orig")) or {}
        link = orig.get("url")
        if not link:
            continue
        try:
            yield int(orig.get("width") or 0), int(orig.get("height") or 0), link
        except (TypeError, ValueError):
            continue
