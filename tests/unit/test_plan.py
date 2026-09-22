import pytest

from manhwatok.domain.errors import InvalidName, ManhwatokError
from manhwatok.domain.plan import RotationItem, clean_rotation, next_item


@pytest.mark.parametrize(
    ("raw", "kind", "value"),
    [
        ("chapter:Solo Leveling", "chapter", "Solo Leveling"),
        ("  Chapter :  151025 ", "chapter", "151025"),
        ("theme:isekai", "theme", "isekai"),
        ("THEME: Regression-Revenge", "theme", "regression-revenge"),
    ],
)
def test_rotation_items_parse_from_text(raw, kind, value):
    item = RotationItem.parse(raw)
    assert (item.kind, item.value) == (kind, value)
    assert str(item) == f"{kind}:{value}"


@pytest.mark.parametrize("raw", ["", "isekai", "list:isekai", ":isekai", "chapters:x"])
def test_anything_but_chapter_or_theme_is_refused(raw):
    with pytest.raises(ManhwatokError, match="chapter:<title> or theme:<name>"):
        RotationItem.parse(raw)


@pytest.mark.parametrize("raw", ["chapter:", "chapter:   ", "theme:"])
def test_an_item_names_something(raw):
    with pytest.raises(ManhwatokError, match="names nothing"):
        RotationItem.parse(raw)


def test_a_theme_item_takes_theme_name_rules():
    with pytest.raises(InvalidName, match="not a theme name"):
        RotationItem.parse("theme:no spaces allowed")


def test_clean_rotation_keeps_order_and_repeats_in_canonical_form():
    assert clean_rotation([" chapter: Solo Leveling", "Theme:Isekai", "chapter:Solo Leveling"]) == [
        "chapter:Solo Leveling",
        "theme:isekai",
        "chapter:Solo Leveling",
    ]


def test_next_item_takes_the_cursors_item_and_moves_on():
    rotation = ["chapter:a", "theme:b", "theme:c"]
    assert next_item(rotation, 0) == (RotationItem.parse("chapter:a"), 1)
    assert next_item(rotation, 1) == (RotationItem.parse("theme:b"), 2)


def test_next_item_wraps_around():
    rotation = ["chapter:a", "theme:b"]
    assert next_item(rotation, 1) == (RotationItem.parse("theme:b"), 0)


def test_a_cursor_past_a_shortened_rotation_wraps_too():
    assert next_item(["theme:b"], 5) == (RotationItem.parse("theme:b"), 0)
    assert next_item(["chapter:a", "theme:b"], 3) == (RotationItem.parse("theme:b"), 0)


def test_an_empty_rotation_has_no_next_item():
    with pytest.raises(ManhwatokError, match="no rotation"):
        next_item([], 0)
