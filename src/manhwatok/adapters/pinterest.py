"""Pictures from a Pinterest search, by way of gallery-dl.

Pinterest has no public search API — the v5 one reaches only your own boards — so this shells
out to gallery-dl, which reads the same search results the website shows. When Pinterest
changes its internals, that is gallery-dl's to patch.

Pinterest's search is a loose text match. For "Log-in Murim manhwa fight scene" its top pins
were Lookism and Northern Blade art: extra words like "fight scene" pull in every popular fight,
whatever it is from. So a search asks for the title and "webtoon" only, and keeps a pin only
when its own texts — title, description, board, alt text, or the labels Pinterest's image
recognition gave it — name the manhwa, by its English or romanized title or one of AniList's
alternative titles. Measured on six murim/action titles, 80 pins each: "<title> webtoon" gave
the most such pins, and "<title> manhwa fight scene" a third as many. A title better known
under another name ("Murim Login") is searched again under that one when the first search
names it too rarely.

Pinterest records no origin for a pin: `source_link` is empty and the domain reads "Uploaded by
user" on essentially everything, so unlike Danbooru there is no artist to credit.
"""

from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus

from manhwatok.adapters.picture_download import download_picture
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Manhwa
from manhwatok.ports.art import ArtOption

SEARCH = "https://www.pinterest.com/search/pins/?q="
LIMIT = 80
MIN_SIDE = 600  # a slide is 1080x1920; Pinterest also serves 236px thumbnails
# Searched alongside the title unless the caller asks for something else ("" = bare title).
DEFAULT_TAG = "webtoon"
ENOUGH = 12  # matching pins below which an alternative title is searched as well
MIN_NAME = 4  # shorter names (after normalising) would match far too much
HINT = "pinterest art needs gallery-dl: uv sync --extra pinterest"

# Runs gallery-dl with these arguments and returns its stdout.
RunFn = Callable[[list[str]], str]


def _gallery_dl(argv: list[str]) -> str:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    if done.returncode != 0:
        detail = (done.stderr or "").strip().splitlines()
        raise ManhwatokError(f"pinterest search failed: {detail[-1] if detail else 'no output'}")
    return done.stdout


def _norm(text: str) -> str:
    """Lowercase words separated by single spaces. NFKC folds the styled letters pinners use
    (𝐊𝐮𝐛𝐞𝐫𝐚) back to plain ones."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[^\w]+|_", " ", text).strip()


def names_of(manhwa: Manhwa) -> list[str]:
    """What a pin may call the title: its English and romanized titles and AniList's
    alternative ones, in Latin letters, normalised, each with and without a leading "the"."""
    names: list[str] = []
    for raw in [manhwa.title, manhwa.romaji, *(manhwa.synonyms or [])]:
        name = _norm(raw)
        if not name.isascii():
            continue  # a pin captioned in Thai or Chinese is rare, and can't be told apart here
        for one in (name, name.removeprefix("the ")):
            if len(one) >= MIN_NAME and one not in names:
                names.append(one)
    return names


def _pin_text(pin: dict) -> str:
    board = pin.get("board") if isinstance(pin.get("board"), dict) else {}
    joined = pin.get("pin_join") if isinstance(pin.get("pin_join"), dict) else {}
    parts = [
        pin.get("title"),
        pin.get("grid_title"),
        pin.get("description"),
        pin.get("seo_alt_text"),
        pin.get("auto_alt_text"),
        board.get("name"),
        *(joined.get("visual_annotation") or []),
    ]
    return " " + _norm(" ".join(p for p in parts if isinstance(p, str))) + " "


def _likes(pin: dict) -> int:
    """Every reaction a pin got (a heart is "1"), which is as close as Pinterest comes to saying
    how well a picture stands for its title."""
    counts = pin.get("reaction_counts") if isinstance(pin.get("reaction_counts"), dict) else {}
    return sum(n for n in counts.values() if isinstance(n, int))


def _names_it(pin: dict, names: list[str]) -> bool:
    text = _pin_text(pin)
    return any(f" {name} " in text for name in names)


class PinterestSource:
    def __init__(
        self,
        run: RunFn | None = None,
        limit: int = LIMIT,
        min_side: int = MIN_SIDE,
        default_tag: str = DEFAULT_TAG,
        enough: int = ENOUGH,
    ) -> None:
        self._run = run or _gallery_dl
        self._limit = limit
        self._min_side = min_side
        self._default_tag = default_tag
        self._enough = enough

    def close(self) -> None:
        """Nothing to close: each search is its own process."""

    def options(self, manhwa: Manhwa, tag: str | None = None) -> list[ArtOption]:
        # None means "no preference", so the default applies; "" means "just the title".
        extra = self._default_tag if tag is None else tag
        names = names_of(manhwa)
        # Keyed by url: a Pinterest search lists each pin more than once, and two searches can
        # find the same pin; the mapping collapses those to one, in first-seen order.
        found: dict[str, tuple[int, int, int]] = {}
        for n, title in enumerate(self._titles(manhwa)):
            if n and len(found) >= self._enough:
                break
            for width, height, link, pin in _pins(self._search(title, extra)):
                if min(width, height) < self._min_side or not _names_it(pin, names):
                    continue
                found.setdefault(link, (width, height, _likes(pin)))
        # Left in Pinterest's own order: that ranking is the only thing here that knows what
        # the search meant. Re-arranging is the caller's choice (ArtOrder).
        return [
            ArtOption(
                label=f"{w}x{h}  {likes} likes  (no artist recorded)",
                url=link,
                width=w,
                height=h,
                likes=likes,
            )
            for link, (w, h, likes) in found.items()
        ]

    @staticmethod
    def _titles(manhwa: Manhwa) -> list[str]:
        """The title, then one alternative worth a second search: the first Latin-letter
        synonym that is not just the title again."""
        titles = [manhwa.title]
        for synonym in manhwa.synonyms or []:
            name = _norm(synonym)
            if name.isascii() and len(name) >= MIN_NAME and name != _norm(manhwa.title):
                titles.append(synonym)
                break
        return titles

    def _search(self, title: str, extra: str) -> str:
        terms = " ".join(part for part in (title, extra) if part).strip()
        argv = ["gallery-dl", "-j", "--range", f"1-{self._limit}", SEARCH + quote_plus(terms)]
        try:
            return self._run(argv)
        except FileNotFoundError as e:
            raise ManhwatokError(HINT) from e
        except subprocess.SubprocessError as e:
            raise ManhwatokError(f"pinterest search failed: {e}") from e

    def fetch(self, option: ArtOption, into: Path) -> Path:
        return download_picture(option.url, into)


def _pins(out: str):
    """The (width, height, url, pin) of every pin in gallery-dl's JSON dump, dupes and all."""
    try:
        entries = json.loads(out or "[]")
    except ValueError as e:
        raise ManhwatokError(f"could not read the pinterest search: {e}") from e
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not (isinstance(entry, list) and entry and isinstance(entry[-1], dict)):
            continue
        pin = entry[-1]
        orig = ((pin.get("images") or {}).get("orig")) or {}
        link = orig.get("url")
        if not link:
            continue
        try:
            yield int(orig.get("width") or 0), int(orig.get("height") or 0), link, pin
        except (TypeError, ValueError):
            continue
