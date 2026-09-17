"""Emojis for a post, derived from the genres its picks share.

An account (or a post) whose emojis are `auto` doesn't carry a fixed string: the emojis come
from the picks, so one account can cover several genres. They are resolved when the caption is
written, not when the post is built, so re-picking a post changes them.
"""

from __future__ import annotations

from collections import Counter

from manhwatok.domain.post import ListPost, PostItem

AUTO = "auto"  # the marker an account or a post stores instead of a fixed emoji string
MAX_EMOJIS = 4  # a caption keeps at most this many, most common genre first

# AniList genres a manhwa can carry; a genre missing here (Ecchi, Hentai) contributes nothing.
GENRE_EMOJIS: dict[str, tuple[str, ...]] = {
    "action": ("🔥", "⚔️"),
    "adventure": ("🗺️", "🧭"),
    "comedy": ("😂",),
    "drama": ("🎭", "💔"),
    "fantasy": ("🐉", "✨"),
    "horror": ("🩸", "👁️"),
    "mahou shoujo": ("🪄", "🌸"),
    "mecha": ("🤖",),
    "music": ("🎵",),
    "mystery": ("🔍", "🕵️"),
    "psychological": ("🧠", "🌀"),
    "romance": ("💗", "🌹"),
    "sci-fi": ("🚀", "🛸"),
    "slice of life": ("🍵", "☀️"),
    "sports": ("⚽", "🏆"),
    "supernatural": ("👻", "🔮"),
    "thriller": ("😱", "🔪"),
}


def emojis_for(items: list[PostItem]) -> str:
    """The emojis of every genre more than half the picks share, commonest first and ties
    alphabetical, capped at MAX_EMOJIS. With no such genre, the commonest genre's emojis alone;
    with no genre this module knows, an empty string."""
    counts = Counter(
        genre
        for item in items
        for genre in {g.strip().casefold() for g in item.manhwa.genres}
        if genre in GENRE_EMOJIS
    )
    if not counts:
        return ""
    ranked = sorted(counts, key=lambda g: (-counts[g], g))
    majority = [g for g in ranked if counts[g] * 2 > len(items)]
    emojis = [e for genre in (majority or ranked[:1]) for e in GENRE_EMOJIS[genre]]
    return "".join(emojis[:MAX_EMOJIS])


def post_emojis(post: ListPost) -> str:
    """What goes after the post's title on TikTok: its own emojis, or, for `auto`, the ones its
    picks earn."""
    return emojis_for(post.items) if post.emojis == AUTO else post.emojis
