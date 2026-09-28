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


CHARACTERS_HELP = "# Characters: add \"| N\" to a line to rank that title's Nth character (default 1)."


def render_draft(
    title: str,
    items: list[PostItem],
    candidates: list[Manhwa],
    cast: dict[int, list] | None = None,
) -> str:
    """Chosen items first (in order), then every other candidate commented out. With `cast`
    (a characters post), each title's characters are listed to choose from."""
    chosen = {item.manhwa.anilist_id for item in items}
    lines = [f"title: {title}", HELP, ""]
    if cast is not None:
        lines[2:2] = [CHARACTERS_HELP] + [
            f"#   {m.anilist_id} {m.title}: " + ", ".join(c.name for c in cast.get(m.anilist_id, []))
            for m in candidates
            if cast.get(m.anilist_id)
        ]
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
        hook = _hook_and_choice(parts[2])[0] if len(parts) == 3 else ""
        items.append(PostItem(manhwa=by_id[anilist_id], hook=hook))
    if not title:
        raise DraftError("the 'title:' line is missing or empty")
    if not items:
        raise DraftError("no titles left — keep at least one line")
    if len(items) > MAX_ITEMS:
        raise DraftError(f"{len(items)} titles — a TikTok post fits at most {MAX_ITEMS}")
    return title, items


def _hook_and_choice(rest: str) -> tuple[str, int | None]:
    """A line's text after its name: the hook, and a trailing "| N" character choice (1-based)
    when there is one. A hook may hold "|" itself; only a bare number at the end is a choice."""
    head, sep, tail = rest.rpartition("|")
    if sep and tail.strip().isdigit():
        return head.strip(), int(tail.strip())
    return rest.strip(), None


def parse_choices(text: str) -> dict[int, int]:
    """A characters draft's choices: title id → which of its characters (0-based), from a
    line's trailing "| N" (1-based there). Lines without one are left out."""
    found: dict[int, int] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.lower().startswith("title:"):
            continue
        parts = line.split("|", 2)
        if len(parts) == 3 and parts[0].strip().isdigit():
            choice = _hook_and_choice(parts[2])[1]
            if choice is not None:
                found[int(parts[0])] = max(choice - 1, 0)
    return found


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
