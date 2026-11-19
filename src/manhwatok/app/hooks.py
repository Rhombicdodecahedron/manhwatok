"""The line under a title on its slide: written by a model when there is one, else the first
sentence of the title's description, cut to fit."""

from __future__ import annotations

from manhwatok.app.post_tools import PostTools
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Manhwa
from manhwatok.domain.text import HOOK_MAX, first_sentence

SHORTER = 20  # how much less a writer that ran long is given the second time
FOREVER = 100 * 365 * 24 * 3600.0  # a written hook does not go stale


def hook_for(manhwa: Manhwa, tools: PostTools) -> str:
    """The hook a new post gives this title. A written one is kept, so a title is written
    once and reads the same in every post; the cut is never kept, so a title built while the
    model was away is written the next time."""
    writer = tools.writer
    if writer is None:
        return first_sentence(manhwa.description)
    key = f"hook:{manhwa.anilist_id}:{writer.model}"
    kept = _kept(tools, key)
    if kept:
        return kept
    for max_len in (HOOK_MAX, HOOK_MAX - SHORTER):
        written = writer.hook(manhwa, max_len)
        if written is None:
            break
        if _fits(written):
            _keep(tools, key, written)
            return written
    return first_sentence(manhwa.description)


def _fits(hook: str) -> bool:
    """One line that fits the slide and says its piece: a hook that trails off is the cut this
    is here to replace."""
    return (
        0 < len(hook) <= HOOK_MAX
        and "\n" not in hook
        and not hook.endswith(("…", "..."))
    )


def _kept(tools: PostTools, key: str) -> str | None:
    if tools.cache is None:
        return None
    try:
        return tools.cache.get(key, FOREVER)
    except ManhwatokError:
        return None


def _keep(tools: PostTools, key: str, hook: str) -> None:
    if tools.cache is None:
        return
    try:
        tools.cache.put(key, hook)
    except ManhwatokError:
        pass  # it is only written again next time
