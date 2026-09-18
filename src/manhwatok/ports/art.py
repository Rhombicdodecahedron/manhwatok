from pathlib import Path
from typing import NamedTuple, Protocol

from manhwatok.domain.models import Manhwa


class ArtOption(NamedTuple):
    """One picture on offer for a title, before it is downloaded."""

    label: str  # what to show in a list, e.g. "vol. 3"
    url: str


class ArtSource(Protocol):
    def options(self, manhwa: Manhwa) -> list[ArtOption]:
        """Pictures this source has for the title, best order first. Empty when it has none."""
        ...

    def fetch(self, option: ArtOption, into: Path) -> Path:
        """Download `option` into `into` and return the file."""
        ...
