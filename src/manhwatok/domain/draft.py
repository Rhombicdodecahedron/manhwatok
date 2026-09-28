"""The editable text form of a post: one title line, then one `id | name | hook` line per pick."""

from __future__ import annotations

from manhwatok.domain.errors import DraftError
from manhwatok.domain.models import Manhwa, PostKind
from manhwatok.domain.post import MAX_GUESS, MAX_ITEMS, PostItem
from manhwatok.domain.text import first_sentence

HELP = (
    "# *word* = accent colour. Delete lines to drop, move lines to reorder, edit text after the 2nd |.\n"
    "# Order = rank. Lines starting with # are ignored.\n"
    "# Save as-is to accept. Delete everything to cancel."
)


def is_empty_draft(text: str) -> bool:
    """True if `text` has no non-comment, non-blank lines (the user deleted everything)."""
    return all(not line.strip() or line.strip().startswith("#") for line in text.splitlines())


def _line(m: Manhwa, hook: str) -> str:
    name = m.title.replace("|", "/")
    return f"{m.anilist_id} | {name} | {hook}"


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


def check_picks(title: str, items: list[PostItem], kind: PostKind = PostKind.LIST) -> None:
    """The rules a post's picks follow when they come from a form instead of a draft file,
    and the ones its kind adds."""
    if not title.strip():
        raise DraftError("give the post a title")
    if not items:
        raise DraftError("pick at least one title")
    most = {PostKind.VERSUS: 2 * MAX_ITEMS, PostKind.GUESS: MAX_GUESS}.get(kind, MAX_ITEMS)
    if len(items) > most:
        if kind in (PostKind.VERSUS, PostKind.GUESS):
            raise DraftError(f"{len(items)} titles — a {kind.value} post fits at most {most}")
        raise DraftError(f"{len(items)} titles — a TikTok post fits at most {most}")
    if kind is PostKind.VERSUS and len(items) % 2:
        raise DraftError(
            f"{len(items)} titles — a versus post takes them in pairs; add or drop one"
        )
    if kind is PostKind.CHARACTERS:
        bare = [i.manhwa.title for i in items if i.character is None]
        if bare:
            raise DraftError(f"pick a character for {', '.join(bare)}")
    ids = [item.manhwa.anilist_id for item in items]
    if len(set(ids)) != len(ids):
        raise DraftError("a title is picked twice")
