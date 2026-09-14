import re

import pytest

from manhwatok.domain.draft import parse_draft, render_draft
from manhwatok.domain.errors import DraftError
from manhwatok.domain.post import PostItem
from tests.unit.fakes import manhwa

CANDIDATES = [
    manhwa(
        anilist_id=128067, title="SSS-Class Revival Hunter", description="He copies skills. More."
    ),
    manhwa(anilist_id=136220, title="Doom Breaker", description="Last man standing. More."),
    manhwa(
        anilist_id=116382, title="The Villainess Turns the Hourglass", description="Executed. More."
    ),
]


def _items(*pairs):
    by_id = {m.anilist_id: m for m in CANDIDATES}
    return [PostItem(manhwa=by_id[i], hook=h) for i, h in pairs]


def test_render_lists_chosen_items_then_comments_out_the_rest():
    text = render_draft("MC *regresses*", _items((136220, "Sent back.")), CANDIDATES)
    lines = text.splitlines()
    assert lines[0] == "title: MC *regresses*"
    assert lines[1].startswith("# *word* = accent colour")
    assert "136220 | Doom Breaker | Sent back." in lines
    assert "# 128067 | SSS-Class Revival Hunter | He copies skills." in lines
    assert "# 116382 | The Villainess Turns the Hourglass | Executed." in lines
    assert lines.index("136220 | Doom Breaker | Sent back.") < lines.index(
        "# 128067 | SSS-Class Revival Hunter | He copies skills."
    )
    assert text.endswith("\n")


def test_render_replaces_pipe_in_title_so_it_cant_shift_the_hook():
    weird = manhwa(anilist_id=1, title="A | B")
    text = render_draft("T", [], [weird])
    assert "1 | A / B | " in text
    assert "A | B" not in text


def test_round_trip_keeps_title_order_and_hooks():
    items = _items((136220, "Sent back."), (128067, "Dies, copies, repeats."))
    title, parsed = parse_draft(render_draft("MC *regresses*", items, CANDIDATES), CANDIDATES)
    assert title == "MC *regresses*"
    assert parsed == items


def test_parse_follows_edited_order_hooks_and_ignores_names():
    text = (
        "title:  Best regressors  \n"
        "# comment\n"
        "\n"
        "116382 | whatever the name says | New hook | with a pipe\n"
        "128067|SSS|\n"
    )
    title, items = parse_draft(text, CANDIDATES)
    assert title == "Best regressors"
    assert [(i.manhwa.anilist_id, i.hook) for i in items] == [
        (116382, "New hook | with a pipe"),
        (128067, ""),
    ]


def test_bare_id_line_gets_empty_hook():
    _, items = parse_draft("title: T\n136220\n", CANDIDATES)
    assert items[0].hook == ""


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("136220 | Doom Breaker | x\n", "'title:' line is missing"),
        ("title:   \n136220 | D | x\n", "'title:' line is missing or empty"),
        ("title: T\ntitle: U\n136220 | D | x\n", "line 2: more than one title line"),
        ("title: T\nDoom Breaker | x\n", "line 2: expected '<id> | <name> | <hook>'"),
        ("title: T\n999 | Nope | x\n", "line 2: 999 is not one of this post's candidates"),
        ("title: T\n136220 | D | x\n136220 | D | y\n", "line 3: 136220 is listed twice"),
        ("title: T\n# 136220 | D | x\n", "no titles left"),
    ],
)
def test_parse_errors(text, message):
    with pytest.raises(DraftError, match=re.escape(message)):
        parse_draft(text, CANDIDATES)


def test_parse_rejects_more_than_33_items():
    many = [manhwa(anilist_id=i, title=f"T{i}") for i in range(1, 35)]
    text = "title: T\n" + "".join(f"{m.anilist_id} | {m.title} | h\n" for m in many)
    with pytest.raises(DraftError, match="34 titles"):
        parse_draft(text, many)
