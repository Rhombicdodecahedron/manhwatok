"""Move a post to another account — when it's uploaded as someone else, say. Its byline follows
when it was the old account's own; its other texts stay the post's."""

from __future__ import annotations

from manhwatok.domain.account import normalize_handle
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.post import ListPost
from manhwatok.ports.posts import PostRepository
from manhwatok.ports.store import AccountRepository


def move_post(
    post_id: str, handle: str, accounts: AccountRepository, posts: PostRepository
) -> ListPost:
    post = posts.get(post_id)
    if post.chapter:
        raise ManhwatokError(
            f"post {post_id} is a chapter post — a chapter post stays on its account"
        )
    new = accounts.get(normalize_handle(handle))
    byline = post.byline
    if post.account:
        try:
            old = accounts.get(post.account)
            if byline == old.byline:
                byline = new.byline
        except ManhwatokError:
            pass  # the old account is gone: the post's own byline stays
    moved = post.model_copy(update={"account": new.handle, "byline": byline})
    posts.save(moved)
    return moved
