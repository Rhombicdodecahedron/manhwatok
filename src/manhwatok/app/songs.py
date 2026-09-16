"""The song note: what to add as the sound when posting. Posts follow their account's song
unless they set their own."""

from __future__ import annotations

from manhwatok.domain.account import effective_song
from manhwatok.domain.errors import AccountNotFound
from manhwatok.domain.post import ListPost
from manhwatok.ports.posts import PostRepository
from manhwatok.ports.store import AccountRepository


def song_for(post: ListPost, accounts: AccountRepository) -> str:
    """The post's effective song; a removed account counts as having no song."""
    account = None
    if post.account:
        try:
            account = accounts.get(post.account)
        except AccountNotFound:
            pass
    return effective_song(post, account)


def set_post_song(post_id: str, song: str | None, posts: PostRepository) -> ListPost:
    """Set the post's own song (None = follow the account's again). Slides and caption don't
    show the song, so nothing is re-rendered."""
    post = posts.get(post_id).model_copy(update={"song": song})
    post = ListPost.model_validate(post.model_dump())  # trims like a fresh post
    posts.save(post)
    return post
