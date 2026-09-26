"""A post's slides as pictures: real pixels on kitty/sixel terminals, coloured blocks
elsewhere. Import this module before the app starts: it asks the terminal what it supports."""

from __future__ import annotations

from pathlib import Path

from PIL import Image as PILImage
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static
from textual_image.widget import Image


def readable_image(path: Path) -> bool:
    try:
        with PILImage.open(path) as img:
            img.verify()
        return True
    except (OSError, SyntaxError, ValueError, PILImage.DecompressionBombError):
        return False


class SlidePreview(Vertical):
    DEFAULT_CSS = """
    SlidePreview { align-horizontal: center; }
    SlidePreview #slide-counter { width: 100%; height: 1; content-align: center middle; }
    SlidePreview #slide-image { width: auto; height: 1fr; }
    SlidePreview #slide-note { width: 100%; height: auto; content-align: center middle; }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self.slides: list[Path] = []
        self.index = 0
        self._note = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="slide-counter")
        yield Image(id="slide-image")
        yield Static("", id="slide-note", markup=False)

    @property
    def current(self) -> Path | None:
        return self.slides[self.index] if self.slides else None

    def show(self, slides: list[Path], note: str = "", index: int = 0) -> None:
        """Show `slides` from the `index`th (the first, when there are fewer now), reading the
        pictures again even when the paths are the same: they may have been rendered anew."""
        self.slides = list(slides)
        self.index = index if 0 <= index < len(self.slides) else 0
        self._note = note
        self._update()

    def step(self, delta: int) -> None:
        if self.slides:
            self.index = (self.index + delta) % len(self.slides)
            self._update()

    def _update(self) -> None:
        counter = self.query_one("#slide-counter", Static)
        image = self.query_one("#slide-image", Image)
        note = self._note
        path = self.current
        counter.update(f"◀ {self.index + 1}/{len(self.slides)} ▶" if path else "")
        if path is not None and not readable_image(path):
            note, path = f"can't show {path.name}", None
        image.image = path
        image.display = path is not None
        self.query_one("#slide-note", Static).update(note)
