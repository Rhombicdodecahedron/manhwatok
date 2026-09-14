"""The editable text form of a post: one title line, then one `id | name | hook` line per pick."""

from __future__ import annotations

from manhwatok.domain.errors import DraftError
from manhwatok.domain.models import Manhwa
from manhwatok.domain.post import MAX_ITEMS, PostItem
from manhwatok.domain.text import first_sentence

HELP = (
    "# *word* = accent colour. Delete lines to drop, move lines to reorder, edit text after the 2nd |.\n"
    "# Order = rank. Lines starting with # are ignored."
)


def _line(m: Manhwa, hook: str) -> str:
    return f"{m.anilist_id} | {m.title} | {hook}"


def render_draft(title: str, items: list[PostItem], candidates: list[Manhwa]) -> str:
    """Chosen items first (in order), then every other candidate commented out."""
    chosen = {item.manhwa.anilist_id for item in items}
    lines = [f"title: {title}", HELP, ""]
    lines += [_line(item.manhwa, item.hook) for item in items]
    lines += [
        "# " + _line(m, first_sentence(m.description))
        for m in candidates
        if m.anilist_id not in chosen
    ]
    return "\n".join(lines) + "\n"


def parse_draft(text: str, candidates: list[Manhwa]) -> tuple[str, list[PostItem]]:
    """Return (title, items) from an edited draft, or raise DraftError naming the bad line."""
    by_id = {m.anilist_id: m for m in candidates}
    title: str | None = None
    items: list[PostItem] = []
    seen: set[int] = set()
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("title:"):
            if title is not None:
                raise DraftError(f"line {n}: more than one title line")
            title = line[len("title:") :].strip()
            continue
        parts = line.split("|", 2)
        try:
            anilist_id = int(parts[0].strip())
        except ValueError:
            raise DraftError(
                f"line {n}: expected '<id> | <name> | <hook>', got {raw.strip()!r}"
            ) from None
        if anilist_id not in by_id:
            raise DraftError(f"line {n}: {anilist_id} is not one of this post's candidates")
        if anilist_id in seen:
            raise DraftError(f"line {n}: {anilist_id} is listed twice")
        seen.add(anilist_id)
        hook = parts[2].strip() if len(parts) == 3 else ""
        items.append(PostItem(manhwa=by_id[anilist_id], hook=hook))
    if not title:
        raise DraftError("the 'title:' line is missing or empty")
    if not items:
        raise DraftError("no titles left — keep at least one line")
    if len(items) > MAX_ITEMS:
        raise DraftError(f"{len(items)} titles — a TikTok post fits at most {MAX_ITEMS}")
    return title, items
