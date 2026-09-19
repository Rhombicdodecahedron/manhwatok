from pathlib import Path
from typing import NamedTuple, Protocol

from manhwatok.domain.models import Manhwa


class ArtOption(NamedTuple):
    """One picture on offer for a title, before it is downloaded."""

    label: str  # what to show in a list, e.g. "vol. 3"
    url: str
    # Pixel size where the source reports it; 0 when it does not (MangaDex names no dimensions
    # without downloading the file). Only used to re-order a list.
    width: int = 0
    height: int = 0
    likes: int = 0  # how many people liked or saved it, where the source says; 0 when not


class ArtSource(Protocol):
    def options(self, manhwa: Manhwa, tag: str | None = None) -> list[ArtOption]:
        """Pictures this source has for the title, best order first. Empty when it has none.

        `tag` narrows the search to pictures also described that way, where the source has such
        a vocabulary; one that does not simply ignores it."""
        ...

    def fetch(self, option: ArtOption, into: Path) -> Path:
        """Download `option` into `into` and return the file."""
        ...
