"""The collaborators every post use case needs, bundled so commands can pass one object."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from manhwatok.ports.posts import CoverSource, PostRepository, SlideRenderer

# Opens text for editing; returns the edited text, or None if the user aborted or changed nothing
# (click.edit's contract).
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
