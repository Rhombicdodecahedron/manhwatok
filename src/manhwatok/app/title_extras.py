"""Fill in what AniList knows about a post's titles that manhwatok did not keep when it saved them.

A post keeps a snapshot of each title from the search it was built from. Fields added since —
all four characters, the alternative titles art is filed under — are missing from older posts,
so they are looked up once by AniList id, in one request, and saved into the post.
"""

from __future__ import annotations

from manhwatok.app.post_tools import PostTools
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.post import ListPost


def refresh_titles(post_id: str, tools: PostTools) -> ListPost:
    """The post, with its older titles filled in and saved. An AniList outage is reported and
    the post returned as it was: what it lacks only makes art searches less exact."""
    post = tools.posts.get(post_id)
    missing = [it.manhwa.anilist_id for it in post.items if it.manhwa.synonyms is None]
    if tools.metadata is None or not missing:
        return post
    try:
        found = tools.metadata.extras(missing)
    except MetadataError as e:
        tools.progress(f"{e} — searching with the titles already known")
        return post
    items = []
    for it in post.items:
        extras = found.get(it.manhwa.anilist_id)
        if extras is not None and it.manhwa.synonyms is None:
            update: dict = {"synonyms": extras.synonyms}
            if extras.character_urls and not it.manhwa.character_urls:
                update["character_urls"] = extras.character_urls
                update["character_url"] = extras.character_urls[0]
            it = it.model_copy(update={"manhwa": it.manhwa.model_copy(update=update)})
        items.append(it)
    post = post.model_copy(update={"items": items})
    tools.posts.save(post)
    return post
