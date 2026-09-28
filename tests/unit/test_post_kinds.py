import pytest

from manhwatok.domain.draft import check_picks
from manhwatok.domain.errors import DraftError
from manhwatok.domain.models import CharacterPick, PostKind
from manhwatok.domain.post import MAX_GUESS, PostItem, cover_kicker
from tests.unit.fakes import chapter_part, chapter_post, manhwa, post


def _items(n, character=False):
    return [
        PostItem(
            manhwa=manhwa(anilist_id=i, title=f"T{i}"),
            character=CharacterPick(name=f"C{i}") if character else None,
        )
        for i in range(1, n + 1)
    ]


def test_old_posts_load_as_list_and_chapter():
    assert post().kind is PostKind.LIST
    data = chapter_post(chapter=chapter_part()).model_dump(mode="json")
    del data["kind"]
    assert type(post()).model_validate(data).kind is PostKind.CHAPTER


@pytest.mark.parametrize(
    ("kind", "n", "slides"),
    [(PostKind.LIST, 5, 7), (PostKind.SIMILAR, 5, 7), (PostKind.VERSUS, 6, 5),
     (PostKind.GUESS, 4, 10), (PostKind.CHARACTERS, 3, 5)],
)
def test_slide_count_by_kind(kind, n, slides):
    assert post(items=_items(n, True), kind=kind).slide_count == slides


@pytest.mark.parametrize(
    ("kind", "n", "label"),
    [(PostKind.LIST, 5, "5 PICKS"), (PostKind.LIST, 1, "1 PICK"),
     (PostKind.SIMILAR, 5, "IF YOU LIKED"), (PostKind.VERSUS, 6, "3 ROUNDS"),
     (PostKind.VERSUS, 2, "1 ROUND"), (PostKind.GUESS, 4, "GUESS 4"),
     (PostKind.CHARACTERS, 3, "TOP 3")],
)
def test_cover_kicker_by_kind(kind, n, label):
    assert cover_kicker(post(items=_items(n, True), kind=kind)) == label


def test_versus_needs_an_even_count():
    with pytest.raises(DraftError, match="pairs"):
        check_picks("T", _items(3), PostKind.VERSUS)
    check_picks("T", _items(4), PostKind.VERSUS)


def test_guess_is_capped():
    with pytest.raises(DraftError, match=str(MAX_GUESS)):
        check_picks("T", _items(MAX_GUESS + 1), PostKind.GUESS)


def test_characters_need_a_character_each():
    with pytest.raises(DraftError, match="T2"):
        check_picks("T", _items(1, True) + [_items(2)[1]], PostKind.CHARACTERS)


def test_a_list_post_still_caps_at_max_items():
    from manhwatok.domain.post import MAX_ITEMS

    with pytest.raises(DraftError, match=str(MAX_ITEMS)):
        check_picks("T", _items(MAX_ITEMS + 1))
