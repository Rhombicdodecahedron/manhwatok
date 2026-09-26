"""A search's candidates, kept between the search and the save: the page only posts back which
titles it picked, in what order, with what hooks. In memory — a restart forgets them, and the
page is told to search again."""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass

from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Manhwa


@dataclass
class Draft:
    id: str
    candidates: list[Manhwa]
    account: str | None
    theme: str | None


class Drafts:
    def __init__(self, keep: int = 20) -> None:
        self._keep = keep
        self._lock = threading.Lock()
        self._drafts: OrderedDict[str, Draft] = OrderedDict()

    def add(self, candidates: list[Manhwa], account: str | None, theme: str | None) -> Draft:
        draft = Draft(secrets.token_urlsafe(8), list(candidates), account, theme)
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
