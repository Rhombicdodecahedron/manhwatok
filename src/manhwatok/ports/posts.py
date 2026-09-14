from datetime import date
from pathlib import Path
from typing import Protocol

from manhwatok.domain.models import Manhwa
from manhwatok.domain.post import ListPost


class PostRepository(Protocol):
    def new_id(self, today: date) -> str: ...

    def folder(self, post_id: str) -> Path: ...

    def save(self, post: ListPost) -> None: ...

    def get(self, post_id: str) -> ListPost: ...

    def list(self) -> list[ListPost]: ...

    def save_draft(self, post_id: str, text: str) -> None: ...

    def load_draft(self, post_id: str) -> str | None: ...

    def clear_draft(self, post_id: str) -> None: ...


class CoverSource(Protocol):
    def get(self, manhwa: Manhwa) -> Path: ...

    def cached(self, manhwa: Manhwa) -> Path | None:
        """Local path of an already-downloaded cover, or None. Never downloads."""
        ...


class SlideRenderer(Protocol):
    def render(
        self, post: ListPost, covers: dict[int, Path | None], out_dir: Path
    ) -> list[Path]: ...
