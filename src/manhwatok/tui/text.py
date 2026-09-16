"""Plain-text pieces the TUI shows (no Textual imports, so they're easy to test)."""

from __future__ import annotations

from manhwatok.app.render_post import rendered_files
from manhwatok.domain.caption import build_caption
from manhwatok.domain.errors import NotRendered, StorageError
from manhwatok.domain.labels import chapter_label
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


def caption_text(post: ListPost, posts: PostRepository) -> tuple[str, bool]:
    """(caption, rendered): caption.txt as rendered, else the caption the post would get."""
    try:
        _, caption = rendered_files(post, posts)
        return caption.read_text(encoding="utf-8").rstrip("\n"), True
    except (NotRendered, OSError, UnicodeDecodeError, StorageError):
        return build_caption(post), False


def post_details(post: ListPost, posts: PostRepository, song: str) -> str:
    """The text beside the slide preview: title, song, caption, picks."""
    who = f"@{post.account}" if post.account else "no account"
    size = "no picks" if post.is_unfinished else f"{post.slide_count} slides"
    own = " (this post's)" if post.song is not None else ""
    lines = [
        plain_title(post.title) or "(untitled)",
        f"{post.id} · {who} · {post_status(post, posts)} · {size}",
        "",
        f"Song: {song}{own}" if song else "Song: –",
    ]
    if post.is_unfinished:
        lines += ["", "no picks yet — press e to pick titles"]
        return "\n".join(lines)
    caption, rendered = caption_text(post, posts)
    lines += ["", "Caption" if rendered else "Caption (not rendered)", caption, "", "Picks"]
    for n, item in enumerate(post.items, 1):
        lines.append(f"{n:>2}. {item.manhwa.title} — {chapter_label(item.manhwa)}")
        if item.hook:
            lines.append(f"    {item.hook}")
    return "\n".join(lines)


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"
