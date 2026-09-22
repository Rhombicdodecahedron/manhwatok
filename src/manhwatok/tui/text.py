"""Plain-text pieces the TUI shows (no Textual imports, so they're easy to test)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from manhwatok.app.render_post import rendered_files
from manhwatok.domain.caption import build_caption
from manhwatok.domain.emoji import AUTO, post_emojis
from manhwatok.domain.errors import NotRendered, StorageError
from manhwatok.domain.labels import chapter_label
from manhwatok.domain.models import ArtStyle, CoverStyle
from manhwatok.domain.post import ListPost
from manhwatok.domain.text import plain_title
from manhwatok.ports.posts import PostRepository


def post_status(post: ListPost, posts: PostRepository) -> str:
    if post.sent_at:
        return "sent"
    if post.exported_at:
        return "exported"
    if post.is_unfinished:
        return "draft"
    try:
        rendered_files(post, posts)
    except NotRendered:
        return "not rendered"
    return "rendered"


def scheduled_text(post: ListPost, zone: str) -> str:
    """When the post goes out, short ("Thu 19:00"), in time zone `zone`; "-" when unscheduled."""
    if post.scheduled_at is None:
        return "-"
    return f"{post.scheduled_at.astimezone(ZoneInfo(zone)):%a %H:%M}"


def caption_text(post: ListPost, posts: PostRepository) -> tuple[str, bool]:
    """(caption, rendered): caption.txt as rendered, else the caption the post would get."""
    try:
        _, caption = rendered_files(post, posts)
        return caption.read_text(encoding="utf-8").rstrip("\n"), True
    except (NotRendered, OSError, UnicodeDecodeError, StorageError):
        return build_caption(post), False


def post_details(post: ListPost, posts: PostRepository, sounds: list[str]) -> str:
    """The text beside the slide preview: title, the account's sounds, art style, cover version,
    emojis, caption, and its picks — or, for a chapter post, which chapter and part it is."""
    who = f"@{post.account}" if post.account else "no account"
    size = "no picks" if post.is_unfinished else f"{post.slide_count} slides"
    part = post.chapter
    lines = [
        plain_title(post.title) or "(untitled)",
        f"{post.id} · {who} · {post_status(post, posts)} · {size}",
        "",
        f"Sounds: {' | '.join(sounds) or '–'}",
    ]
    if part:
        which = f"Chapter {part.number}" if part.number else "Oneshot"
        if part.parts > 1:
            which += f" · part {part.part}/{part.parts}"
        lines.append(f"{which} · {len(part.panels)} panels of {part.pages} pages ({part.language})")
    if post.art is not ArtStyle.NONE and not part:
        lines.append(f"Art: {post.art.value}")
    if post.cover is not CoverStyle.FAN:
        lines.append(f"Cover: {post.cover.value}")
    emojis = post_emojis(post)
    if emojis:
        lines.append(f"Emojis: {emojis}{' (auto)' if post.emojis == AUTO else ''}")
    if post.is_unfinished:
        lines += ["", "no picks yet — press e to pick titles"]
        return "\n".join(lines)
    caption, rendered = caption_text(post, posts)
    lines += ["", "Caption" if rendered else "Caption (not rendered)", caption]
    if part:
        return "\n".join(lines)
    lines += ["", "Picks"]
    for n, item in enumerate(post.items, 1):
        lines.append(f"{n:>2}. {item.manhwa.title} — {chapter_label(item.manhwa)}")
        if item.hook:
            lines.append(f"    {item.hook}")
    return "\n".join(lines)


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"
