from manhwatok.domain.models import Manhwa, Status

_WORD = {
    Status.FINISHED: "completed",
    Status.RELEASING: "ongoing",
    Status.HIATUS: "hiatus",
    Status.CANCELLED: "cancelled",
    Status.NOT_YET_RELEASED: "upcoming",
    Status.UNKNOWN: "",
}


def chapter_label(m: Manhwa) -> str:
    """Short slide/CLI label, e.g. '135 chapters · completed' or 'ongoing · ch. 212'."""
    word = _WORD[m.status]
    n = m.chapter_count
    if n is None:
        return word or "chapters unknown"
    count = f"{n} chapter" if n == 1 else f"{n} chapters"
    if m.status in (Status.FINISHED, Status.CANCELLED):
        return f"{count} · {word}"
    if word:
        return f"{word} · ch. {n}"
    return count
