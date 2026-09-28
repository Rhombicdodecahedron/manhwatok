import pytest

from manhwatok.domain.models import ChapterCoverStyle, CoverStyle
from tests.unit.fakes import chapter_part, chapter_post, post


def test_a_list_post_offers_the_list_covers():
    p = post()
    assert p.cover_styles == [s.value for s in CoverStyle]
    assert p.chosen_cover == "fan"
    assert p.with_cover("podium").cover is CoverStyle.PODIUM


def test_a_chapter_post_offers_the_chapter_covers():
    p = chapter_post(chapter=chapter_part())
    assert p.cover_styles == [s.value for s in ChapterCoverStyle]
    assert p.chosen_cover == "focus"
    chosen = p.with_cover("tease")
    assert chosen.chapter_cover is ChapterCoverStyle.TEASE and chosen.cover is CoverStyle.FAN


@pytest.mark.parametrize(("make", "wrong"), [(post, "cinematic"), (lambda: chapter_post(chapter=chapter_part()), "hero")])
def test_a_cover_of_the_other_kind_is_refused_by_name(make, wrong):
    with pytest.raises(ValueError, match="pick one of"):
        make().with_cover(wrong)


def test_an_older_post_without_a_chapter_cover_loads_as_focus():
    p = chapter_post(chapter=chapter_part())
    data = p.model_dump(mode="json")
    del data["chapter_cover"]
    assert type(p).model_validate(data).chapter_cover is ChapterCoverStyle.FOCUS
