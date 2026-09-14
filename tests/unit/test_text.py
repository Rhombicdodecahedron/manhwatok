import pytest

from manhwatok.domain.text import accent_spans, first_sentence, plain_title


@pytest.mark.parametrize(
    ("desc", "expected"),
    [
        ("Jay's the perfect student. He has straight As.", "Jay's the perfect student."),
        ("Is he back? Yes.", "Is he back?"),
        ("Version 2.0 of the hero arrives. Then more.", "Version 2.0 of the hero arrives."),
        ("No terminator here\nSecond paragraph.", "No terminator here"),
        ("  \n  ", ""),
        ("", ""),
    ],
)
def test_first_sentence(desc, expected):
    assert first_sentence(desc) == expected


def test_first_sentence_cuts_long_text_at_a_word_with_ellipsis():
    desc = "word " * 40 + "end."
    hook = first_sentence(desc, max_len=30)
    assert len(hook) <= 30
    assert hook.endswith("…")
    assert not hook[:-1].endswith(" ")
    assert hook[:-1].split() == ["word"] * len(hook[:-1].split())


def test_first_sentence_cuts_a_single_huge_word():
    hook = first_sentence("x" * 200, max_len=20)
    assert hook == "x" * 19 + "…"


def test_accent_spans_marks_starred_words():
    assert accent_spans("MC *regresses* for *revenge*") == [
        ("MC ", False),
        ("regresses", True),
        (" for ", False),
        ("revenge", True),
    ]


def test_accent_spans_keeps_a_lone_star_literal():
    assert accent_spans("5* rated") == [("5* rated", False)]


def test_plain_title_drops_markers():
    assert plain_title("MC *regresses* for *revenge*") == "MC regresses for revenge"
