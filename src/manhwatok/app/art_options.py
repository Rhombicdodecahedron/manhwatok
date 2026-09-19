"""Pictures another catalogue has for one title of a post, and picking one of them.

AniList gives manhwatok a single cover per title. MangaDex usually has the whole run of volume
covers, so this is the way to swap the one AniList happened to pick for the one you want. A
chosen picture is downloaded and then handed to `set_item_art`, so it ends up exactly where a
hand-picked file would — the renderer needs to know nothing about where it came from.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from manhwatok.app.item_art import find_index, set_item_art
from manhwatok.app.post_tools import PostTools
from manhwatok.app.title_extras import refresh_titles
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import ArtOrder
from manhwatok.ports.art import ArtOption, ArtSource


def list_art(
    post_id: str,
    anilist_id: int,
    tools: PostTools,
    source: ArtSource,
    tag: str | None = None,
    order: ArtOrder = ArtOrder.RELEVANCE,
) -> list[ArtOption]:
    """What `source` has for this title of the post. `tag` narrows it where the source
    understands such a thing, and `order` rearranges what comes back."""
    post = refresh_titles(post_id, tools)
    found = source.options(post.items[find_index(post, anilist_id)].manhwa, tag)
    return arrange(found, order)


SLIDE = 1080 / 1920  # what a picture's width/height is measured against for ArtOrder.PORTRAIT


def arrange(options: list[ArtOption], order: ArtOrder) -> list[ArtOption]:
    """Re-order `options`. Sorting is stable, so anything a source reports no size for keeps its
    place among its equals and falls to the end rather than being dropped."""
    if order is ArtOrder.RELEVANCE:
        return list(options)
    if order is ArtOrder.SIZE:
        return sorted(options, key=lambda o: -(o.width * o.height))
    if order is ArtOrder.POPULAR:
        return sorted(options, key=lambda o: -o.likes)
    return sorted(options, key=_off_slide_shape)


def _off_slide_shape(option: ArtOption) -> float:
    """How far from a slide's proportions this picture is; unmeasurable ones sort last."""
    if option.width <= 0 or option.height <= 0:
        return float("inf")
    return abs(option.width / option.height - SLIDE)


def use_art(
    post_id: str, anilist_id: int, option: ArtOption, tools: PostTools, source: ArtSource
) -> Path:
    """Download `option` and keep it as this title's art. Returns where it was kept."""
    post = tools.posts.get(post_id)
    find_index(post, anilist_id)  # fail before downloading, not after
    with tempfile.TemporaryDirectory(prefix="manhwatok-art-") as tmp:
        got = source.fetch(option, Path(tmp))
        return set_item_art(post_id, anilist_id, got, tools)


TRIES = 5  # downloads per title before giving up on finding one no other title has


def fill_art(
    post_id: str,
    tools: PostTools,
    source: ArtSource,
    tag: str | None = None,
    order: ArtOrder = ArtOrder.RELEVANCE,
    pick: int = 1,
    replace: bool = False,
) -> int:
    """`use_art` for every title at once: the `pick`th picture `source` has for each, after
    `order`. Titles that already have picked art keep it unless `replace`, so fixing a few by
    hand survives a later fill. A failed search stops the lot, since it would fail every title
    the same way. Returns how many titles got a picture.

    No two titles in a post get the same picture. A generic search word can outweigh the title,
    and then several titles' first results are the same pin — so a title passes over any
    picture another title already has, by address or by content (a repin moves address), and
    takes the next one. A title with nothing left to take keeps its style's own art."""
    post = refresh_titles(post_id, tools)
    folder = tools.posts.folder(post_id)
    refill = [item for item in post.items if replace or not item.custom_art]
    refilled = {item.manhwa.anilist_id for item in refill}
    taken = {
        _digest(folder / item.custom_art)
        for item in post.items
        if item.custom_art and item.manhwa.anilist_id not in refilled
    }
    seen: set[str] = set()
    filled = 0
    for item in refill:
        manhwa = item.manhwa
        options = arrange(source.options(manhwa, tag), order)
        if len(options) < pick:
            found = f"only {len(options)}" if options else "nothing"
            tools.progress(f"{manhwa.title}: found {found} — keeping its own art")
            continue
        problem = "every picture it found is already used in this post"
        chosen = None
        tries = 0
        for option in options[pick - 1 :]:
            if option.url in seen or tries == TRIES:
                continue
            seen.add(option.url)
            tries += 1
            with tempfile.TemporaryDirectory(prefix="manhwatok-art-") as tmp:
                try:
                    got = source.fetch(option, Path(tmp))
                except ManhwatokError as e:
                    problem = str(e)
                    continue
                digest = _digest(got)
                if digest in taken:
                    continue
                if tools.has_text is not None and tools.has_text(got):
                    problem = "every picture it found has words on it"
                    continue
                set_item_art(post_id, manhwa.anilist_id, got, tools)
            taken.add(digest)
            chosen = option
            break
        if chosen is None:
            tools.progress(f"{manhwa.title}: {problem} — keeping its own art")
            continue
        tools.progress(f"{manhwa.title}: {chosen.label}")
        filled += 1
    return filled


def looks(path: Path) -> tuple[int, tuple[int, int, int]] | None:
    """What a picture looks like, whatever its size or encoding: a 64-bit difference hash of its
    shapes and its average colour. None when it can't be read."""
    try:
        with Image.open(path) as img:
            rgb = img.convert("RGB")
    except (OSError, UnidentifiedImageError):
        return None
    grey = rgb.convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = bits << 1 | (grey[row * 9 + col] > grey[row * 9 + col + 1])
    mean = rgb.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    return bits, mean


def same_picture(a, b) -> bool:
    """Whether two `looks` are one picture: a repin at another size, or re-encoded."""
    if a is None or b is None:
        return False
    shapes = bin(a[0] ^ b[0]).count("1")
    colour = max(abs(x - y) for x, y in zip(a[1], b[1]))
    return shapes <= 6 and colour <= 24


def _digest(path: Path) -> str:
    """What a picture file is, whatever it is called. A missing one matches nothing."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""
