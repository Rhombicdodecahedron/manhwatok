"""The quad style's four pictures per title: scenes, picked art, then characters.

By default scenes only fill what a title's characters leave. Asking for a search by name
(`render --art quad --source pins --tag "fight scene"`) fills all four squares with its scenes
instead, and characters only stand in where it finds too few. Kept scenes lead the grid either
way, so a later plain render keeps what the search found.

AniList lists a title's characters most favourited first, but only some have a picture and
many titles have fewer than four. Titles saved before the style existed kept just the first
one, so `refresh_titles` looks the rest up. What is still missing is searched for (Pinterest by
default, most liked first, wide ones skipped, and any with words on them — speech bubbles,
captions — passed over) and kept in the post's folder as
scene-<id>-<n> files, so a re-render downloads nothing and exporting keeps working after the
source changes.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from manhwatok.app.art_options import TRIES, arrange, looks, same_picture
from manhwatok.app.post_tools import PostTools
from manhwatok.app.title_extras import refresh_titles
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import QUAD_PICTURES, ArtOrder
from manhwatok.domain.post import ListPost, PostItem
from manhwatok.ports.art import ArtSource

PREFIX = "scene-"


@dataclass(frozen=True)
class SceneSearch:
    """Where the gaps' scenes come from and how they are chosen, as `fill_art` takes them."""

    source: ArtSource | None
    tag: str | None = None
    order: ArtOrder = ArtOrder.RELEVANCE
    pick: int = 1  # skip the first pick-1 results
    replace: bool = False  # drop the scenes already kept and search again
    # Scenes for all four squares, rather than only those the characters and picked art leave.
    # A search the user asked for by name means this: they want its pictures on the slide.
    fill: bool = False


def prepare_quad(post_id: str, tools: PostTools, search: SceneSearch | None = None) -> None:
    """Make sure each title of the post has its characters known and its gaps filled."""
    # Most liked first: the pictures people keep are the ones that stand for the title.
    search = search or SceneSearch(tools.scenes, order=ArtOrder.POPULAR)
    post = refresh_titles(post_id, tools)
    _fill_scenes(post, tools, search)


def kept_scenes(item: PostItem, folder: Path) -> list[Path]:
    """The item's scene files that are still on disk, in grid order."""
    return [folder / name for name in item.scenes if (folder / name).is_file()]


def _gaps(item: PostItem, folder: Path, fill: bool) -> int:
    """Squares still wanting a scene: all but those holding one already when `fill`, else what
    the characters and picked art leave too."""
    have = len(kept_scenes(item, folder))
    if not fill:
        has_pick = bool(item.custom_art) and (folder / item.custom_art).is_file()
        have += len(item.manhwa.characters[:QUAD_PICTURES]) + has_pick
    return max(0, QUAD_PICTURES - have)


def _fill_scenes(post: ListPost, tools: PostTools, search: SceneSearch) -> None:
    folder = tools.posts.folder(post.id)
    items = list(post.items)
    if search.replace:
        for i, it in enumerate(items):
            for path in kept_scenes(it, folder):
                path.unlink(missing_ok=True)
            items[i] = it.model_copy(update={"scenes": []})
    if search.source is None:
        _save_items(post, items, tools)
        return
    # No picture twice in one post, by what it looks like (a repin can be resized or
    # re-encoded): picked art and every scene already kept.
    taken = [looks(folder / it.custom_art) for it in items if it.custom_art]
    taken += [looks(p) for it in items for p in kept_scenes(it, folder)]
    if tools.has_text is None:
        tools.progress("pictures aren't checked for speech bubbles — uv sync --extra pinterest")
    for i, it in enumerate(items):
        need = _gaps(it, folder, search.fill)
        if not need:
            continue
        try:
            options = arrange(search.source.options(it.manhwa, search.tag), search.order)
        except ManhwatokError as e:
            # A search that fails fails for every title (no gallery-dl, no network): say so once.
            tools.progress(f"{e} — quad slides fill their gaps with the cover")
            break
        names = [p.name for p in kept_scenes(it, folder)]
        wanted, tries = need, 0
        for option in options[search.pick - 1 :]:
            if need == 0 or tries == need * 3 + TRIES:
                break
            if option.width > option.height:  # sizes the source doesn't report are 0, kept
                continue
            tries += 1
            with tempfile.TemporaryDirectory(prefix="manhwatok-scene-") as tmp:
                try:
                    got = search.source.fetch(option, Path(tmp))
                except ManhwatokError:
                    continue
                seen = looks(got)
                if seen is None or any(same_picture(seen, t) for t in taken):
                    continue
                if tools.has_text is not None and tools.has_text(got):
                    continue  # a speech bubble, a caption, a meme: not a picture of the title
                name = _free_name(folder, it.manhwa.anilist_id, got.suffix.lower() or ".jpg")
                folder.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(got, folder / name)
            taken.append(seen)
            names.append(name)
            need -= 1
        items[i] = it.model_copy(update={"scenes": names})
        got = wanted - need
        note = " — the rest repeat its other pictures" if need else ""
        tools.progress(f"{it.manhwa.title}: {got} of {wanted} scenes found{note}")
    _save_items(post, items, tools)


def _free_name(folder: Path, anilist_id: int, suffix: str) -> str:
    n = 1
    while any(folder.glob(f"{PREFIX}{anilist_id}-{n}.*")):
        n += 1
    return f"{PREFIX}{anilist_id}-{n}{suffix}"


def _save_items(post: ListPost, items: list[PostItem], tools: PostTools) -> None:
    if items != post.items:
        tools.posts.save(post.model_copy(update={"items": items}))
