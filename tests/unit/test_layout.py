import pytest

from manhwatok.adapters.fonts import body, display
from manhwatok.adapters.layout import (
    SAFE,
    Box,
    fit_inside,
    fit_words,
    layout_cover,
    layout_end,
    layout_item,
    plain_words,
    stack_up,
    words_of,
    wrap_words,
)
from manhwatok.domain.post import DEFAULT_CTA_FOLLOW, DEFAULT_CTA_TITLE
from manhwatok.domain.text import accent_spans

LONG_NAME = "The Reincarnated Assassin Who Became the Strongest Swordmaster of the Northern Duchy"
LONG_HOOK = "He wakes up again " * 25


def _word_text(word) -> str:
    return "".join(t for t, _ in word)


def _line_text(line) -> str:
    return " ".join(_word_text(w) for w in line)


def _end(names):
    return layout_end(names, DEFAULT_CTA_TITLE, DEFAULT_CTA_FOLLOW)


def test_stack_up_ends_at_bottom_with_gaps():
    assert stack_up([10, 20, 30], bottom=100, gap=5) == [30, 45, 70]


def test_wrap_respects_width_and_breaks_huge_words():
    font = body(40)
    lines = wrap_words(plain_words("short words " * 10 + "x" * 80), font, 400)
    assert all(font.getlength(_line_text(line)) <= 400 for line in lines)
    assert "".join(_word_text(w) for line in lines for w in line).count("x") == 80


def test_words_of_keeps_punctuation_attached_across_span_boundaries():
    """A span boundary without whitespace must not become a word boundary (no stray space)."""
    words = words_of(accent_spans("MC *regresses*, then *revenge*!"))
    assert [_word_text(w) for w in words] == ["MC", "regresses,", "then", "revenge!"]
    assert [a for _, a in words[0]] == [False]
    assert [a for _, a in words[1]] == [True, False]  # "regresses" accent, "," not
    assert [a for _, a in words[2]] == [False]
    assert [a for _, a in words[3]] == [True, False]  # "revenge" accent, "!" not


def test_words_of_merges_a_word_split_by_one_accent_run():
    [word] = words_of(accent_spans("*re*gression"))
    assert word == (("re", True), ("gression", False))


def test_fitted_line_has_no_stray_space_before_punctuation():
    fitted = fit_words(
        words_of(accent_spans("MC *regresses*, then *revenge*!")), display, 900, 4, 124, 72
    )
    text = " ".join(fitted.line_text(i) for i in range(len(fitted.lines)))
    assert " ," not in text
    assert " !" not in text


def test_fit_shrinks_before_giving_up():
    fitted = fit_words(plain_words(LONG_NAME.upper()), display, 870, 2, 84, 56)
    assert len(fitted.lines) <= 2
    assert fitted.font.size < 84


def test_fit_ellipsizes_at_min_size():
    fitted = fit_words(plain_words(LONG_HOOK), body, 870, 3, 40, 32)
    assert fitted.font.size == 32
    assert len(fitted.lines) == 3
    assert fitted.line_text(2).endswith("…")
    assert fitted.width <= 870


def test_accent_flags_survive_wrapping():
    fitted = fit_words(
        words_of(accent_spans("MC *REGRESSES* FOR *REVENGE*")), display, 900, 4, 124, 72
    )
    flags = {}
    for line in fitted.lines:
        for word in line:
            flags[_word_text(word)] = any(a for _, a in word)
    assert flags == {"MC": False, "REGRESSES": True, "FOR": False, "REVENGE": True}


def test_fit_inside_keeps_aspect_centred_top_aligned():
    box = fit_inside(460, 650, Box(230, 250, 620, 700))
    assert box.h == 700
    assert box.w == round(460 * 700 / 650)
    assert box.y == 250
    assert box.x == 230 + (620 - box.w) // 2


@pytest.mark.parametrize(
    ("name", "hook"),
    [("Kubera", ""), ("Doom Breaker", "Sent back ten years."), (LONG_NAME, LONG_HOOK)],
)
def test_item_layout_stays_in_safe_area(name, hook):
    layout = layout_item(33, name, "ongoing · ch. 1234", hook)
    assert all(SAFE.contains(b) for b in layout.text_boxes())
    assert layout.cover_area.y == SAFE.y
    assert layout.cover_area.bottom <= layout.rank.box.y - 40
    assert (layout.hook is None) == (hook == "")


def test_item_text_is_bottom_anchored():
    layout = layout_item(1, "Kubera", "ongoing", "A hook.")
    assert layout.hook.box.bottom == SAFE.bottom


@pytest.mark.parametrize("count", [1, 5, 33])
def test_cover_layout_stays_in_safe_area(count):
    layout = layout_cover("*" + LONG_NAME + "* and " + LONG_NAME, count)
    assert all(SAFE.contains(b) for b in layout.text_boxes())
    assert len(layout.bar) == count
    assert len(layout.title.text.lines) <= 4


@pytest.mark.parametrize("n", [1, 5, 33])
def test_end_layout_stays_in_safe_area(n):
    layout = _end([LONG_NAME] * n)
    assert all(SAFE.contains(b) for b in layout.text_boxes())


def test_end_layout_collapses_overflow_into_more_row():
    layout = _end([f"Title {i}" for i in range(33)])
    last = layout.rows[-1]
    assert last.number is None
    assert last.name.text.line_text(0).startswith("+")
    shown = len(layout.rows) - 1
    assert last.name.text.line_text(0) == f"+{33 - shown} more"


def test_end_layout_uses_big_text_for_short_lists():
    layout = _end(["A", "B"])
    assert layout.rows[0].name.text.font.size == 44
    assert [r.number.text.line_text(0) for r in layout.rows] == ["1", "2"]


def test_end_layout_shrinks_the_list_so_a_long_name_fits():
    layout = _end(["I Became the Tyrant of a Defense Game", "Kubera"])
    first = layout.rows[0].name.text
    assert first.font.size < 44
    assert "…" not in first.line_text(0)


def test_end_layout_ellipsizes_huge_names_instead_of_shrinking_below_34():
    layout = _end([LONG_NAME])
    name = layout.rows[0].name.text
    assert name.font.size == 34
    assert name.line_text(0).endswith("…")


@pytest.mark.parametrize("n", [1, 3, 5])
def test_end_layout_centres_a_short_list_between_title_and_follow(n):
    layout = _end([f"Title {i}" for i in range(n)])
    boxes = [
        b for row in layout.rows for b in ([row.number.box] if row.number else []) + [row.name.box]
    ]
    above = min(b.y for b in boxes) - layout.title.box.bottom
    below = layout.follow.box.y - max(b.bottom for b in boxes)
    assert abs(above - below) <= 2


def test_end_layout_full_list_still_fits_between_title_and_follow():
    layout = _end([f"Title {i}" for i in range(33)])
    assert layout.rows[0].name.box.y > layout.title.box.bottom
    assert layout.rows[-1].name.box.bottom < layout.follow.box.y


def test_end_layout_uses_the_given_cta_texts():
    layout = layout_end(["A"], "Seen *these*?", "More tomorrow")
    title_words = [w for line in layout.title.text.lines for w in line]
    assert [_word_text(w) for w in title_words] == ["SEEN", "THESE?"]
    assert [any(a for _, a in w) for w in title_words] == [False, True]
    assert layout.follow.text.line_text(0) == "MORE TOMORROW"


def test_end_layout_wraps_a_long_follow_line_onto_two_lines():
    layout = layout_end(["A"], "T", "Follow @manhwa.daily for part 2 every Friday")
    follow = layout.follow.text
    assert len(follow.lines) == 2
    assert "…" not in follow.line_text(1)
    assert layout.follow.box.bottom == 1560


@pytest.mark.parametrize("n", [1, 5, 33])
def test_end_layout_with_long_custom_ctas_stays_in_safe_area(n):
    layout = layout_end([LONG_NAME] * n, LONG_NAME + " *" + LONG_NAME + "*", LONG_NAME)
    assert all(SAFE.contains(b) for b in layout.text_boxes())


def test_cover_kicker_is_singular_for_one_pick():
    assert layout_cover("T", 1).kicker.text.line_text(0) == "1 PICK"
    assert layout_cover("T", 5).kicker.text.line_text(0) == "5 PICKS"


# --- panel art (Phase 5) ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "hook"),
    [("Kubera", ""), ("Doom Breaker", "Sent back ten years."), (LONG_NAME, LONG_HOOK)],
)
def test_panel_layout_keeps_text_where_it_was(name, hook):
    """Only the image box changes shape; the text stack is the same one the cover style uses."""
    upright = layout_item(33, name, "ongoing · ch. 1234", hook)
    panel = layout_item(33, name, "ongoing · ch. 1234", hook, panel=True)
    assert panel.text_boxes() == upright.text_boxes()
    assert all(SAFE.contains(b) for b in panel.text_boxes())


def test_panel_image_box_is_wide_and_spans_the_safe_width():
    panel = layout_item(1, "Kubera", "ongoing", "A hook.").cover_area
    wide = layout_item(1, "Kubera", "ongoing", "A hook.", panel=True).cover_area
    assert wide.w > wide.h  # landscape, unlike the upright cover card
    assert wide.w > panel.w
    assert wide.x == SAFE.x and wide.w == SAFE.w


def test_panel_image_box_is_centred_in_the_space_above_the_text():
    layout = layout_item(1, "Kubera", "ongoing", "A hook.", panel=True)
    free_top, free_bottom = SAFE.y, layout.rank.box.y - 40
    above = layout.cover_area.y - free_top
    below = free_bottom - layout.cover_area.bottom
    assert abs(above - below) <= 1
    assert above > 0


@pytest.mark.parametrize(
    ("name", "hook"),
    [("Kubera", ""), ("Doom Breaker", "Sent back ten years."), (LONG_NAME, LONG_HOOK)],
)
def test_panel_image_box_never_collides_with_the_text(name, hook):
    layout = layout_item(33, name, "ongoing · ch. 1234", hook, panel=True)
    assert SAFE.contains(layout.cover_area)
    assert layout.cover_area.bottom <= layout.rank.box.y - 40
    assert layout.cover_area.h > 0
