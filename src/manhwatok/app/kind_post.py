"""Building the post kinds beyond a plain list: where their titles come from."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from manhwatok.app.suggest import _drop_blocked, _fill_chapters
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import CharacterPick, Manhwa, SearchQuery
from manhwatok.domain.post import PostItem
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


def character_choices(
    items: list[PostItem], metadata: MetadataSource
) -> dict[int, list[CharacterPick]]:
    """Each pick's pictured characters, most favourited first: what a characters post offers."""
    return metadata.characters([i.manhwa.anilist_id for i in items])


def with_characters(
    items: list[PostItem], metadata: MetadataSource, choice: dict[int, int] | None = None
) -> list[PostItem]:
    """Each pick with its character: `choice[id]` (an index into its choices), else its most
    favourited. The title's pictures are refreshed so the character's index finds its image;
    a hook left blank says who the character is."""
    cast = character_choices(items, metadata)
    out = []
    for item in items:
        picks = cast.get(item.manhwa.anilist_id) or []
        if not picks:
            raise ManhwatokError(f"{item.manhwa.title} has no pictured characters on AniList")
        wanted = (choice or {}).get(item.manhwa.anilist_id, 0)
        chosen = picks[min(max(wanted, 0), len(picks) - 1)]
        m = item.manhwa.model_copy(
            update={
                "character_urls": [p.image_url for p in picks],
                "character_url": picks[0].image_url,
            }
        )
        hook = item.hook or " · ".join(x for x in (chosen.role.title(), m.title) if x)
        out.append(item.model_copy(update={"manhwa": m, "character": chosen, "hook": hook}))
    return out


def carry_characters(
    before: list[PostItem],
    items: list[PostItem],
    metadata: MetadataSource | None,
    choices: dict[int, int] | None = None,
) -> list[PostItem]:
    """A characters post's picks after an edit: each title keeps the character it had, unless
    `choices` names another; a title new to the post (or re-chosen) is looked up in
    `metadata`. Without `metadata` a new title is left bare, for the pick check to refuse."""
    had = {i.manhwa.anilist_id: i for i in before if i.character is not None}
    choices = choices or {}
    kept: dict[int, PostItem] = {}
    lookup: list[PostItem] = []
    for item in items:
        m_id = item.manhwa.anilist_id
        if m_id in had and m_id not in choices:
            old = had[m_id]
            kept[m_id] = item.model_copy(update={"manhwa": old.manhwa, "character": old.character})
        elif item.character is not None and m_id not in choices:
            kept[m_id] = item
        else:
            lookup.append(item)
    if lookup and metadata is not None:
        for item in with_characters(lookup, metadata, choices):
            kept[item.manhwa.anilist_id] = item
    return [kept.get(i.manhwa.anilist_id, i) for i in items]
