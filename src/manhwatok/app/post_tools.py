"""The collaborators every post use case needs, bundled so commands can pass one object."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from manhwatok.ports.art import ArtSource
from manhwatok.ports.metadata import MetadataSource
from manhwatok.ports.posts import CoverSource, PostRepository, SlideRenderer

# Opens text for editing; returns the edited text (even if unchanged), or None if the editor
# failed or was aborted (non-zero exit).
EditorFn = Callable[[str], str | None]
ProgressFn = Callable[[str], None]


def _noop(_: str) -> None:
    pass


@dataclass
class PostTools:
    posts: PostRepository
    covers: CoverSource
    renderer: SlideRenderer
    editor: EditorFn
    progress: ProgressFn = _noop
    # The quad style's extras: AniList, to look up characters of titles saved with only one,
    # and where scenes for the gaps are searched. Without them it uses what it already has.
    metadata: MetadataSource | None = None
    scenes: ArtSource | None = None
    # Whether a downloaded picture has words on it (speech bubbles, captions); None = unchecked.
    has_text: Callable[[Path], bool] | None = None
