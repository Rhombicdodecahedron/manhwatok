from manhwatok.domain.post import ListPost
from manhwatok.domain.text import plain_title


def build_caption(post: ListPost) -> str:
    """TikTok caption: plain title, numbered picks, hashtags."""
    picks = "\n".join(f"{i}. {item.manhwa.title}" for i, item in enumerate(post.items, 1))
    return f"{plain_title(post.title)}\n\n{picks}\n\n{post.hashtags}"
