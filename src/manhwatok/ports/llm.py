"""What a language model does for a post: write a title's hook, and judge a picture for it.

Both answer None when they can't say — no server, a reply that makes no sense — and that is
never an error: whoever asked falls back to what it did before there was a model."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, Protocol

from manhwatok.domain.models import Manhwa


class HookWriter(Protocol):
    model: str  # which model answers: what it said is kept under this name

    def hook(self, manhwa: Manhwa, max_len: int) -> str | None:
        """One sentence that sells the title, aimed at `max_len` characters or fewer."""
        ...


class ArtVerdict(NamedTuple):
    ok: bool  # the right series, and nothing laid over the art
    score: float  # 0–10: how good the art is
    reason: str


class ArtJudge(Protocol):
    model: str

    def judge(self, picture: Path, manhwa: Manhwa, reference: Path | None) -> ArtVerdict | None:
        """Whether `picture` is good art of this title. `reference` is art known to be of it
        (its cover), to compare against."""
        ...
