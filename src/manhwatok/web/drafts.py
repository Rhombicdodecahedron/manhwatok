"""A search's candidates, kept between the search and the save: the page only posts back which
titles it picked, in what order, with what hooks. In memory — a restart forgets them, and the
page is told to search again."""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Manhwa


@dataclass
class Draft:
    id: str
    candidates: list[Manhwa]
    account: str | None
    theme: str | None
    kind: str = "list"  # a PostKind value: what the save makes of the picks
    seed: Manhwa | None = None  # a similar search's "if you liked" title
    cast: dict = field(default_factory=dict)  # a characters search's choices, by title id


class Drafts:
    def __init__(self, keep: int = 20) -> None:
        self._keep = keep
        self._lock = threading.Lock()
        self._drafts: OrderedDict[str, Draft] = OrderedDict()

    def add(
        self,
        candidates: list[Manhwa],
        account: str | None,
        theme: str | None,
        kind: str = "list",
        seed: Manhwa | None = None,
        cast: dict | None = None,
    ) -> Draft:
        draft = Draft(
            secrets.token_urlsafe(8), list(candidates), account, theme, kind, seed, cast or {}
        )
        with self._lock:
            self._drafts[draft.id] = draft
            while len(self._drafts) > self._keep:
                self._drafts.popitem(last=False)
        return draft

    def take(self, draft_id: str) -> None:
        """Retire a search once it made a post, so a double click or Back can't make another."""
        with self._lock:
            self._drafts.pop(draft_id, None)

    def get(self, draft_id: str) -> Draft:
        with self._lock:
            draft = self._drafts.get(draft_id)
        if draft is None:
            raise ManhwatokError("this search is gone — search again")
        return draft


@dataclass
class ArtList:
    id: str
    post_id: str
    anilist_id: int
    source: str  # an ArtSourceName value
    options: list  # list[ArtOption]


class ArtLists:
    """The pictures a source offered for one title, kept until one is chosen."""

    def __init__(self, keep: int = 20) -> None:
        self._keep = keep
        self._lock = threading.Lock()
        self._lists: OrderedDict[str, ArtList] = OrderedDict()

    def add(self, post_id: str, anilist_id: int, source: str, options: list) -> ArtList:
        found = ArtList(secrets.token_urlsafe(8), post_id, anilist_id, source, list(options))
        with self._lock:
            self._lists[found.id] = found
            while len(self._lists) > self._keep:
                self._lists.popitem(last=False)
        return found

    def get(self, list_id: str) -> ArtList:
        with self._lock:
            found = self._lists.get(list_id)
        if found is None:
            raise ManhwatokError("this list is gone — find pictures again")
        return found
