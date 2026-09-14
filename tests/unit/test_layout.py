import pytest

from manhwatok.adapters.fonts import anton, inter_semibold
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
from manhwatok.domain.text import accent_spans

LONG_NAME = "The Reincarnated Assassin Who Became the Strongest Swordmaster of the Northern Duchy"
LONG_HOOK = "He wakes up again " * 25


def _word_text(word) -> str:
    return "".join(t for t, _ in word)


def _line_text(line) -> str:
    return " ".join(_word_text(w) for w in line)


def test_stack_up_ends_at_bottom_with_gaps():
    assert stack_up([10, 20, 30], bottom=100, gap=5) == [30, 45, 70]


def test_wrap_respects_width_and_breaks_huge_words():
    font = inter_semibold(40)
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
        words_of(accent_spans("MC *regresses*, then *revenge*!")), anton, 900, 4, 124, 72
    )
    text = " ".join(fitted.line_text(i) for i in range(len(fitted.lines)))
    assert " ," not in text
    assert " !" not in text


def test_fit_shrinks_before_giving_up():
    fitted = fit_words(plain_words(LONG_NAME.upper()), anton, 870, 2, 84, 56)
    assert len(fitted.lines) <= 2
    assert fitted.font.size < 84


def test_fit_ellipsizes_at_min_size():
    fitted = fit_words(plain_words(LONG_HOOK), inter_semibold, 870, 3, 40, 32)
    assert fitted.font.size == 32
    assert len(fitted.lines) == 3
    assert fitted.line_text(2).endswith("…")
    assert fitted.width <= 870


def test_accent_flags_survive_wrapping():
    fitted = fit_words(
        words_of(accent_spans("MC *REGRESSES* FOR *REVENGE*")), anton, 900, 4, 124, 72
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
    layout = layout_end([LONG_NAME] * n)
    assert all(SAFE.contains(b) for b in layout.text_boxes())


def test_end_layout_collapses_overflow_into_more_row():
    layout = layout_end([f"Title {i}" for i in range(33)])
    last = layout.rows[-1]
    assert last.number is None
    assert last.name.text.line_text(0).startswith("+")
    shown = len(layout.rows) - 1
    assert last.name.text.line_text(0) == f"+{33 - shown} more"


def test_end_layout_uses_big_text_for_short_lists():
    layout = layout_end(["A", "B"])
    assert layout.rows[0].name.text.font.size == 44
    assert [r.number.text.line_text(0) for r in layout.rows] == ["1", "2"]
