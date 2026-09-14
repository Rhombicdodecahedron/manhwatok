import pytest

from manhwatok.domain.labels import chapter_label
from manhwatok.domain.models import Manhwa, Status


def _m(status, chapters=None, latest=None):
    return Manhwa(anilist_id=1, title="A", romaji="A", status=status, chapters=chapters, latest_chapter=latest)


@pytest.mark.parametrize(
    ("manhwa", "label"),
    [
        (_m(Status.FINISHED, chapters=135), "135 chapters · completed"),
        (_m(Status.FINISHED, chapters=1), "1 chapter · completed"),
        (_m(Status.CANCELLED, chapters=40), "40 chapters · cancelled"),
        (_m(Status.RELEASING, latest=212), "ongoing · ch. 212"),
        (_m(Status.HIATUS, latest=101), "hiatus · ch. 101"),
        (_m(Status.RELEASING), "ongoing"),
        (_m(Status.NOT_YET_RELEASED), "upcoming"),
        (_m(Status.UNKNOWN, chapters=40), "40 chapters"),
        (_m(Status.UNKNOWN), "chapters unknown"),
    ],
)
def test_chapter_label(manhwa, label):
    assert chapter_label(manhwa) == label
