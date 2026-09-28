from manhwatok.domain.emoji import post_emojis
from manhwatok.domain.models import PostKind
from manhwatok.domain.post import ListPost
from manhwatok.domain.text import plain_title

TITLE_MAX = 90  # TikTok's title field


def upload_title(post: ListPost) -> str:
    """TikTok's title field: the plain title, then the post's emojis (`auto`: the ones its picks
    earn). A title too long for the field loses words from its end; the emojis stay."""
    chosen = post_emojis(post)
    emojis = f" {chosen}" if chosen else ""
    words = plain_title(post.title).split()
    while words and len(" ".join(words)) + len(emojis) > TITLE_MAX:
        words.pop()
    return (" ".join(words) + emojis).strip()


def upload_description(post: ListPost) -> str:
    """TikTok's description: what the post holds, then hashtags. A chapter post names its
    chapter and part; a list post numbers its picks."""
    if post.chapter:
        part = post.chapter
        which = f"{part.manhwa_title} — chapter {part.number}"
        if part.parts > 1:
            which += f" · part {part.part}/{part.parts}"
        return f"{which}\n\n{post.hashtags}".strip()
    if post.kind is PostKind.GUESS:
        answers = "\n".join(f"{i}. {it.manhwa.title}" for i, it in enumerate(post.items, 1))
        lead = f"Guess all {len(post.items)} before you swipe!"
        return f"{lead}\n.\n.\n.\nAnswers:\n{answers}\n\n{post.hashtags}".strip()
    if post.kind is PostKind.VERSUS:
        its = post.items
        rounds = "\n".join(
            f"{n}. {its[i].manhwa.title} vs {its[i + 1].manhwa.title}"
            for n, i in enumerate(range(0, len(its) - 1, 2), 1)
        )
        return f"{rounds}\n\n{post.hashtags}".strip()
    picks = "\n".join(f"{i}. {item.manhwa.title}" for i, item in enumerate(post.items, 1))
    if post.kind is PostKind.SIMILAR and post.seed is not None:
        return f"If you liked {post.seed.title}, read:\n{picks}\n\n{post.hashtags}".strip()
    return f"{picks}\n\n{post.hashtags}".strip()


def build_caption(post: ListPost) -> str:
    """caption.txt, for posting by hand: the title line, then the description."""
    return f"{upload_title(post)}\n\n{upload_description(post)}"
