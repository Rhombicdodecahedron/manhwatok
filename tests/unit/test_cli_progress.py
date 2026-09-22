import io
import re

from manhwatok.cli import ProgressLine
from manhwatok.ports.chapters import PageCount


def unstyle(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _count(done, total=4):
    return PageCount("chapter 13", "page", done, total)


def test_a_terminal_redraws_one_line_as_pages_land():
    out = io.StringIO()
    line = ProgressLine(out, tty=True)
    line(_count(1))
    line(_count(2))
    text = out.getvalue()
    assert "\n" not in text
    assert text.count("\r") == 2
    assert "2/4" in text.rsplit("\r", 1)[1]


def test_the_bar_fills_with_the_pages():
    out = io.StringIO()
    line = ProgressLine(out, tty=True, width=8)
    line(_count(2))
    assert "████░░░░" in out.getvalue()


def test_the_last_page_ends_the_line():
    out = io.StringIO()
    line = ProgressLine(out, tty=True)
    line(_count(4))
    assert out.getvalue().endswith("\n")


def test_a_message_after_an_unfinished_bar_starts_on_its_own_line():
    out = io.StringIO()
    line = ProgressLine(out, tty=True)
    line(_count(1))
    line("cutting panels")
    assert unstyle(out.getvalue()).endswith("1/4\n  cutting panels\n")


def test_close_ends_an_unfinished_bar_once():
    out = io.StringIO()
    line = ProgressLine(out, tty=True)
    line(_count(1))
    line.close()
    line.close()
    assert unstyle(out.getvalue()).endswith("1/4\n")


def test_without_a_terminal_every_message_is_its_own_line():
    out = io.StringIO()
    line = ProgressLine(out, tty=False)
    line(_count(1))
    line("cutting panels")
    assert out.getvalue() == "  chapter 13: page 1 of 4\n  cutting panels\n"
