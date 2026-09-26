from datetime import date
from pathlib import Path
from typing import NamedTuple, Protocol

from manhwatok.domain.models import Manhwa
from manhwatok.domain.post import ListPost


class PostRepository(Protocol):
    def new_id(self, today: date) -> str: ...

    def folder(self, post_id: str) -> Path: ...

    def save(self, post: ListPost) -> None: ...

    def get(self, post_id: str) -> ListPost: ...

    def list(self) -> list[ListPost]: ...

    def stamp(self) -> tuple:
        """Changes whenever a post is added, saved, deleted or rendered, from anywhere."""
        ...

    def save_draft(self, post_id: str, text: str) -> None: ...

    def load_draft(self, post_id: str) -> str | None: ...

    def clear_draft(self, post_id: str) -> None: ...


class SlideArt(NamedTuple):
    """The images one manhwa slide can draw with. Any may be missing: no cover means a plain
    accent background, and no banner or character means the cover stands in for it. `custom` is
    art the user picked by hand, and beats all of them."""

    cover: Path | None
    banner: Path | None
    character: Path | None = None
    custom: Path | None = None
    # The quad style's pictures, in grid order: the title's characters, then its scenes. The
    # renderer tops it up from `custom` and `cover` when it has fewer than four.
    gallery: tuple[Path, ...] = ()


class CoverSource(Protocol):
    def get(self, manhwa: Manhwa) -> Path: ...

    def cached(self, manhwa: Manhwa) -> Path | None:
        """Local path of an already-downloaded cover, or None. Never downloads."""
        ...

    def get_banner(self, manhwa: Manhwa) -> Path: ...

    def get_character(self, manhwa: Manhwa, index: int = 0) -> Path: ...

    def cached_banner(self, manhwa: Manhwa) -> Path | None:
        """Local path of an already-downloaded banner, or None. Never downloads."""
        ...

    def cached_character(self, manhwa: Manhwa, index: int = 0) -> Path | None:
        """Local path of an already-downloaded character image, or None. Never downloads."""
        ...


class SlideRenderer(Protocol):
    def render(
        self, post: ListPost, art: dict[int, SlideArt], out_dir: Path
    ) -> list[Path]: ...
