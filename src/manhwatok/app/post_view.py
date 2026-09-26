"""How a post reads in a list or a detail view: its status, when it goes out, its caption.
Shared by the TUI and the web app."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from manhwatok.app.render_post import rendered_files
from manhwatok.domain.caption import build_caption
from manhwatok.domain.errors import NotRendered, StorageError
from manhwatok.domain.post import ListPost
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


def sent_text(post: ListPost, zone: str) -> str:
    """The day the post went out, short ("18 Sep"), in time zone `zone`; "-" when unsent."""
    if post.sent_at is None:
        return "-"
    return f"{post.sent_at.astimezone(ZoneInfo(zone)):%d %b}"


def caption_text(post: ListPost, posts: PostRepository) -> tuple[str, bool]:
    """(caption, rendered): caption.txt as rendered, else the caption the post would get."""
    try:
        _, caption = rendered_files(post, posts)
        return caption.read_text(encoding="utf-8").rstrip("\n"), True
    except (NotRendered, OSError, UnicodeDecodeError, StorageError):
        return build_caption(post), False
