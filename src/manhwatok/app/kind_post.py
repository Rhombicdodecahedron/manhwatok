"""Building the post kinds beyond a plain list: where their titles come from."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from manhwatok.app.suggest import _drop_blocked, _fill_chapters
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Manhwa, SearchQuery
from manhwatok.domain.text import clean_names
from manhwatok.ports.metadata import ChapterSource, MetadataSource
from manhwatok.ports.store import HistoryRepository


def _noop(_: str) -> None:
    pass


def similar_title(seed: Manhwa) -> str:
    return f"If you liked *{seed.title}*"


def similar_candidates(
    seed: Manhwa,
    account: Account | None,
    metadata: MetadataSource,
    chapters: ChapterSource | None,
    history: HistoryRepository,
    now: datetime,
    allow_repeats: bool = False,
    progress: Callable[[str], None] = _noop,
) -> list[Manhwa]:
    """The seed's AniList recommendations, less what the account blocks or posted within its
    repeat window, as a list search's results are."""
    found = metadata.recommendations(seed.anilist_id)
    if account is not None:
        query = SearchQuery(
            exclude_genres=clean_names(account.block_genres),
            exclude_tags=clean_names(account.block_tags),
        )
        found = _drop_blocked(found, query)
        if not allow_repeats:
            recent = history.recent(account.handle, now - timedelta(days=account.repeat_days))
            found = [m for m in found if m.anilist_id not in recent]
    if not found:
        raise ManhwatokError(
            f"no recommendations for {seed.title} on AniList"
            + ("" if account is None else " that the account hasn't posted or blocked")
        )
    return _fill_chapters(found, chapters, progress)
