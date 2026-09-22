"""An account's next post, made from its rotation without a person in the loop: the picks and
the art are chosen as the defaults would choose them, and the post is rendered, ready for
someone to look over (in the TUI, or with `edit` and `render`) before it goes out.

What each item makes is what the hand-driven commands make: `chapter build <title> --account`
for a chapter item, `build --account --theme <name>` with its first picks kept for a theme
item, then `render --source <the account's art source>`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from manhwatok.app.build_post import prefill_items, store_new_post
from manhwatok.app.chapter_post import (
    ChapterTools,
    build_chapter_post,
    pick_source,
    refresh_chapters,
    resolve_title,
)
from manhwatok.app.context import AppContext
from manhwatok.app.delete_post import delete_post
from manhwatok.app.render_post import render_from_source, render_post
from manhwatok.app.suggest import suggest_for_account
from manhwatok.domain.account import Account, normalize_handle
from manhwatok.domain.chapter import next_part
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Manhwa
from manhwatok.domain.plan import CHAPTER, RotationItem, next_item
from manhwatok.domain.post import ListPost

LANGUAGE = "en"  # the language a chapter item publishes in
THEME_TITLES = 12  # how many titles a theme item searches for, as `build`'s default --limit

WarnFn = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def make_next_post(
    ctx: AppContext, handle: str, now: datetime, warn: WarnFn = _noop
) -> ListPost:
    """Make and render the post the account's rotation is at, and move the rotation on.

    A chapter item whose title has no part left to build (even after asking its source for new
    chapters) is passed over with a `warn`, and the next item is tried; after one full pass with
    nothing made, it gives up. The cursor is saved only once a post exists, so a failure leaves
    the rotation where it was. Progress goes to `ctx.tools.progress`."""
    account = ctx.store.accounts.get(normalize_handle(handle))
    cursor = account.rotation_cursor
    for _ in range(max(len(account.rotation), 1)):
        item, cursor = next_item(account.rotation, cursor)
        post = _make(ctx, account, item, now, warn)
        if post is not None:
            ctx.store.accounts.update(account.model_copy(update={"rotation_cursor": cursor}))
            return post
    raise ManhwatokError(
        f"nothing left to post in {account.display}'s rotation — every chapter in it is built; "
        f"add a title or a theme with: manhwatok account set {account.display} --rotation ..."
    )


def _make(
    ctx: AppContext, account: Account, item: RotationItem, now: datetime, warn: WarnFn
) -> ListPost | None:
    if item.kind == CHAPTER:
        return _chapter_post(ctx, account, item.value, now, warn)
    return _theme_post(ctx, account, item.value, now)


def _chapter_post(
    ctx: AppContext, account: Account, title: str, now: datetime, warn: WarnFn
) -> ListPost | None:
    """The title's next part, or None (and a warning) when every part of it is built."""
    progress = ctx.tools.progress
    manhwa = resolve_title(title, ctx.metadata, ctx.store.cache)
    ct = pick_source(manhwa, ctx.chapter_tools, LANGUAGE, None, progress)
    if not _has_next(manhwa, ct, now):
        warn(
            f"{manhwa.title}: every listed chapter is built — skipping to the next rotation item"
        )
        return None
    post, _ = build_chapter_post(manhwa, ctx.tools, ct, account, now, language=LANGUAGE)
    return post


def _has_next(manhwa: Manhwa, ct: ChapterTools, now: datetime) -> bool:
    """Whether a part is left to build. When the chapters on record are all built (or none
    are on record yet), the source is asked for its list first: an ongoing title has new
    chapters most weeks, and a rotation shouldn't pass over them until someone refreshes."""
    parts = ct.chapters.parts(manhwa.anilist_id, LANGUAGE, ct.source)
    known = ct.chapters.chapters(manhwa.anilist_id, LANGUAGE, ct.source)
    if known and next_part(known, parts) is not None:
        return True
    known = refresh_chapters(manhwa, ct, now, LANGUAGE)
    return next_part(known, parts) is not None


def _theme_post(ctx: AppContext, account: Account, name: str, now: datetime) -> ListPost:
    """A list post of the theme's first picks for the account, its art filled from the
    account's art source if it has one, rendered. A post whose art or render fails is removed,
    so trying again doesn't leave a half-made one behind."""
    tools = ctx.tools
    theme = ctx.store.themes.get(name)
    candidates = suggest_for_account(
        theme.to_query(THEME_TITLES),
        account,
        ctx.metadata,
        ctx.chapters,
        ctx.store.history,
        now,
        progress=tools.progress,
    )
    if not candidates:
        raise ManhwatokError(
            f"theme {theme.name}: no titles left for {account.display} — every match was "
            f"posted in the last {account.repeat_days} days, or the theme is too narrow"
        )
    post = store_new_post(
        candidates,
        theme.title,
        prefill_items(candidates),
        account,
        None,
        None,
        tools.posts,
        now,
        theme=theme.name,
    )
    try:
        if account.art_source is None:
            render_post(post.id, tools)
        else:
            source = account.art_source
            filled, _ = render_from_source(post.id, tools, ctx.art_sources[source])
            if filled is not None:
                tools.progress(f"new {source.value} for {filled} of {len(post.items)} titles")
    except BaseException:
        try:
            delete_post(post.id, tools.posts)
        except ManhwatokError:
            pass
        raise
    return tools.posts.get(post.id)
