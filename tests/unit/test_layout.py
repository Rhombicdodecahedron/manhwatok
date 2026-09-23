import pytest

from manhwatok.adapters.fonts import body, display
from manhwatok.adapters.layout import (
    SAFE,
    SLIDE_H,
    SLIDE_W,
    Box,
    byline_of,
    fit_inside,
    fit_words,
    layout_chapter_cover,
    layout_cover,
    layout_end,
    layout_item,
    plain_words,
    stack_up,
    words_of,
    wrap_words,
)
from manhwatok.domain.models import ArtStyle
from manhwatok.domain.post import DEFAULT_CTA_FOLLOW, DEFAULT_CTA_TITLE
from manhwatok.domain.text import accent_spans

LONG_NAME = "The Reincarnated Assassin Who Became the Strongest Swordmaster of the Northern Duchy"
BY = "by @manhwa.daily.reads"
LONG_HOOK = "He wakes up again " * 25


def _word_text(word) -> str:
    return "".join(t for t, _ in word)


def _line_text(line) -> str:
    return " ".join(_word_text(w) for w in line)


def _end(names, byline=""):
    return layout_end(names, DEFAULT_CTA_TITLE, DEFAULT_CTA_FOLLOW, byline)


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


def test_layouts_have_no_byline_without_an_account():
    assert layout_cover("T", 5).byline is None
    assert layout_item(1, "Kubera", "ongoing", "A hook.").byline is None
    assert _end(["Kubera"]).byline is None


@pytest.mark.parametrize("count", [1, 12, 33])
def test_cover_byline_sits_centred_below_the_safe_area(count):
    layout = layout_cover("*" + LONG_NAME + "* and " + LONG_NAME, count, BY)
    assert layout.byline is not None
    assert layout.byline.align == "center"
    assert layout.byline.box.y >= SAFE.bottom  # under everything laid out in the safe area
    assert layout.byline.box.bottom <= SLIDE_H - 120  # clear of TikTok's own caption and buttons
    assert len(layout.byline.text.lines) == 1
    assert all(SAFE.contains(b) for b in layout.text_boxes())


@pytest.mark.parametrize("art", list(ArtStyle))
def test_every_slide_signs_itself_in_the_same_place(art):
    """The byline is a mark on the post, so it never moves between slides."""
    cover = layout_cover("T", 3, BY).byline
    item = layout_item(33, LONG_NAME, "ongoing · ch. 1234", LONG_HOOK, art=art, byline=BY).byline
    end = _end([LONG_NAME] * 5, byline=BY).byline
    assert cover is not None
    assert (item.box, end.box) == (cover.box, cover.box)


@pytest.mark.parametrize("art", list(ArtStyle))
def test_the_byline_costs_the_slide_nothing(art):
    """It sits below the safe area, so the text and the art are laid out as they always were."""
    plain = layout_item(1, "Kubera", "ongoing", "A hook.", art=art)
    signed = layout_item(1, "Kubera", "ongoing", "A hook.", art=art, byline=BY)
    assert signed.text_boxes() == plain.text_boxes()
    assert signed.cover_area == plain.cover_area
    assert signed.hook.box.bottom < signed.byline.box.y


@pytest.mark.parametrize("art", [ArtStyle.SCENE, ArtStyle.QUAD])
def test_full_bleed_art_keeps_the_whole_slide(art):
    signed = layout_item(1, "Kubera", "ongoing", "A hook.", art=art, byline=BY)
    assert signed.cover_area == Box(0, 0, SLIDE_W, SLIDE_H)


@pytest.mark.parametrize("n", [1, 12, 33])
def test_end_layout_with_a_byline_stays_in_the_safe_area(n):
    layout = _end([LONG_NAME] * n, byline=BY)
    assert all(SAFE.contains(b) for b in layout.text_boxes())
    assert layout.follow.box.bottom < layout.byline.box.y
    assert layout.text_boxes() == _end([LONG_NAME] * n).text_boxes()


# --- panel art (Phase 5) ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "hook"),
    [("Kubera", ""), ("Doom Breaker", "Sent back ten years."), (LONG_NAME, LONG_HOOK)],
)
def test_panel_layout_keeps_text_where_it_was(name, hook):
    """Only the image box changes shape; the text stack is the same one the cover style uses."""
    upright = layout_item(33, name, "ongoing · ch. 1234", hook)
    panel = layout_item(33, name, "ongoing · ch. 1234", hook, art=ArtStyle.PANEL)
    assert panel.text_boxes() == upright.text_boxes()
    assert all(SAFE.contains(b) for b in panel.text_boxes())


def test_panel_image_box_is_wide_and_spans_the_safe_width():
    panel = layout_item(1, "Kubera", "ongoing", "A hook.").cover_area
    wide = layout_item(1, "Kubera", "ongoing", "A hook.", art=ArtStyle.PANEL).cover_area
    assert wide.w > wide.h  # landscape, unlike the upright cover card
    assert wide.w > panel.w
    assert wide.x == SAFE.x and wide.w == SAFE.w


def test_panel_image_box_is_centred_in_the_space_above_the_text():
    layout = layout_item(1, "Kubera", "ongoing", "A hook.", art=ArtStyle.PANEL)
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
    layout = layout_item(33, name, "ongoing · ch. 1234", hook, art=ArtStyle.PANEL)
    assert SAFE.contains(layout.cover_area)
    assert layout.cover_area.bottom <= layout.rank.box.y - 40
    assert layout.cover_area.h > 0


# --- character art box -----------------------------------------------------------------------


def test_character_image_box_uses_the_whole_space_above_the_text():
    layout = layout_item(1, "Kubera", "ongoing", "A hook.", art=ArtStyle.CHARACTER)
    area = layout.cover_area
    assert (area.x, area.w) == (SAFE.x, SAFE.w)
    assert area.y == SAFE.y
    assert area.bottom == layout.rank.box.y - 40


def test_character_image_box_is_bigger_than_the_cover_card():
    plain = layout_item(1, "Kubera", "ongoing", "A hook.").cover_area
    char = layout_item(1, "Kubera", "ongoing", "A hook.", art=ArtStyle.CHARACTER).cover_area
    assert char.w > plain.w
    assert char.w * char.h > plain.w * plain.h


@pytest.mark.parametrize(
    ("name", "hook"),
    [("Kubera", ""), ("Doom Breaker", "Sent back ten years."), (LONG_NAME, LONG_HOOK)],
)
def test_character_image_box_stays_clear_of_the_text(name, hook):
    layout = layout_item(33, name, "ongoing · ch. 1234", hook, art=ArtStyle.CHARACTER)
    assert SAFE.contains(layout.cover_area)
    assert layout.cover_area.bottom <= layout.rank.box.y - 40
    assert all(SAFE.contains(b) for b in layout.text_boxes())


# --- scene art -------------------------------------------------------------------------------


def test_scene_image_box_is_the_whole_slide():
    layout = layout_item(1, "Kubera", "ongoing", "A hook.", art=ArtStyle.SCENE)
    assert layout.cover_area == Box(0, 0, SLIDE_W, SLIDE_H)


@pytest.mark.parametrize(
    ("name", "hook"),
    [("Kubera", ""), ("Doom Breaker", "Sent back ten years."), (LONG_NAME, LONG_HOOK)],
)
def test_scene_image_box_does_not_shrink_when_the_title_and_hook_are_long(name, hook):
    """The other styles give the image whatever the text leaves; this one is the slide itself."""
    layout = layout_item(33, name, "ongoing · ch. 1234", hook, art=ArtStyle.SCENE)
    assert layout.cover_area == Box(0, 0, SLIDE_W, SLIDE_H)


@pytest.mark.parametrize(
    ("name", "hook"),
    [("Kubera", ""), ("Doom Breaker", "Sent back ten years."), (LONG_NAME, LONG_HOOK)],
)
def test_scene_layout_keeps_text_where_it_was(name, hook):
    upright = layout_item(33, name, "ongoing · ch. 1234", hook)
    scene = layout_item(33, name, "ongoing · ch. 1234", hook, art=ArtStyle.SCENE)
    assert scene.text_boxes() == upright.text_boxes()
    assert all(SAFE.contains(b) for b in scene.text_boxes())


def test_quad_image_box_is_the_whole_slide():
    layout = layout_item(1, LONG_NAME, "ongoing", LONG_HOOK, art=ArtStyle.QUAD)
    assert layout.cover_area == Box(0, 0, SLIDE_W, SLIDE_H)


# --- chapter cover ------------------------------------------------------------------------------


@pytest.mark.parametrize("parts", [1, 2, 6])
def test_chapter_cover_layout_stays_in_the_safe_area(parts):
    layout = layout_chapter_cover(LONG_NAME, "1024.5", 1, parts, BY)
    assert all(SAFE.contains(b) for b in layout.text_boxes())
    assert len(layout.bar) == parts


def test_chapter_cover_kicker_names_the_chapter_and_the_part():
    layout = layout_chapter_cover("The Boxer", "12", 2, 3)
    assert layout.kicker.text.line_text(0) == "CHAPTER 12 · PART 2/3"


def test_chapter_cover_kicker_drops_the_part_when_there_is_only_one():
    assert layout_chapter_cover("The Boxer", "12", 1, 1).kicker.text.line_text(0) == "CHAPTER 12"


def test_the_chapter_cover_bar_lights_the_part_being_posted():
    assert layout_chapter_cover("The Boxer", "12", 3, 4).lit == 2  # 0-based segment


def test_the_chapter_cover_signs_itself_where_every_other_slide_does():
    assert layout_chapter_cover("The Boxer", "12", 1, 1, BY).byline.box == byline_of(BY).box


def test_a_long_manhwa_name_shrinks_rather_than_leaving_the_safe_area():
    layout = layout_chapter_cover(LONG_NAME + " " + LONG_NAME, "12", 1, 1)
    assert len(layout.title.text.lines) <= 4
    assert all(SAFE.contains(b) for b in layout.text_boxes())


# --- chapter end slide ---------------------------------------------------------------------


def test_chapter_end_puts_the_title_above_the_big_line_and_the_follow_below():
    from manhwatok.adapters.layout import layout_chapter_end

    layout = layout_chapter_end("Solo Leveling", "Chapter *2* done", "Follow for chapter 3", BY)
    assert layout.name.text.line_text(0) == "SOLO LEVELING"
    lines = layout.title.text.lines
    whole = " ".join(layout.title.text.line_text(i) for i in range(len(lines)))
    assert whole == "CHAPTER 2 DONE"  # it may wrap; the words are what matter
    assert layout.follow.text.line_text(0) == "FOLLOW FOR CHAPTER 3"
    assert layout.name.box.bottom <= layout.title.box.y  # the title reads first
    assert layout.title.box.bottom <= layout.follow.box.y
    assert layout.byline is not None


def test_chapter_end_keeps_every_block_inside_the_safe_area():
    from manhwatok.adapters.layout import SAFE, layout_chapter_end

    layout = layout_chapter_end(LONG_NAME, "Part *2* next", "Follow for part 3")
    for box in layout.text_boxes():
        assert box.y >= SAFE.y and box.bottom <= SAFE.bottom, box
        assert box.x >= SAFE.x and box.x + box.w <= SAFE.x + SAFE.w, box


def test_chapter_end_centres_its_three_blocks():
    from manhwatok.adapters.layout import layout_chapter_end

    layout = layout_chapter_end("The Boxer", "Chapter *13* done", "Follow for chapter 14")
    assert [p.align for p in (layout.name, layout.title, layout.follow)] == ["center"] * 3
