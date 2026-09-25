import pytest
from PIL import Image

from manhwatok.adapters.panel_junk import PanelJunk, junk_from

TITLES = ["Solo Leveling", "Na Honjaman Level Up"]
H = 1000


def _line(text, top=500, score=0.95):
    return ([[0, top], [100, top], [100, top + 20], [0, top + 20]], text, score)


def _flat(empty):
    """How much of each row is margin, on a piece whose top is drawing and the rest, `empty`
    of it, bare margin."""
    return [1.0 if row >= H * (1 - empty) else 0.1 for row in range(H)]


@pytest.mark.parametrize(
    ("found", "empty"),
    [
        ([_line("Translator: JJoelle"), _line("Editor: Sami"), _line("QA/QC: Jen Lee")], 0.9),
        ([_line("READ AT ASURASCANS.COM")], 0.6),  # a website banner
        ([_line("join our discord"), _line("discord.gg/xyz")], 0.1),  # a full-art ad
        ([_line("www.mangareader.to")], 0.7),
        ([_line("TRANSLATED BY: SHOCKSWORD")], 0.6),
        ([_line("brought to you by"), _line("ded reads")], 0.6),
        ([_line("Art: DUBU(REDICE STUDIO)"), _line("Original Story: Chugong")], 0.2),
        ([_line("SOLO LEVELING")], 0.8),  # the title card
        ([_line("Solo"), _line("Leveling")], 0.8),  # a title set on two lines
        ([_line("Soka", top=500), _line("Leveling", top=600), _line("IT ALL STARTS", 700)], 0.6),
        ([_line("Na Honjaman Level Up")], 0.7),  # under another of its names
        ([_line("To Be Continued...")], 0.9),  # what follows is the end card
    ],
)
def test_pages_that_are_not_the_story_are_junk(found, empty):
    assert junk_from(found, TITLES, _flat(empty)) is not None


@pytest.mark.parametrize(
    ("found", "empty"),
    [
        ([], 0.9),  # nothing to read
        ([_line("MY NAME IS SUNG JINWOO.")], 0.7),  # a bubble on a dark page
        ([_line("asurascans.com", score=0.9)], 0.2),  # a watermark over a story panel
        ([_line("I'M A SOLO LEVELING HUNTER")], 0.3),  # the title said in the story
        ([_line("SOLO LEVELING")], 0.3),  # the title drawn into busy art
        ([_line("Translator: JJoelle", score=0.3)], 0.9),  # read with no confidence
    ],
)
def test_story_pages_are_not_junk(found, empty):
    assert junk_from(found, TITLES, _flat(empty)) is None


def test_junk_starts_at_its_first_line_so_the_story_above_it_can_be_kept():
    found = [
        _line("I MUST HAVE COURAGE", top=200),
        _line("Translator: JJoelle", top=700),
        _line("Editor: Sami", top=760),
    ]
    assert junk_from(found, TITLES, _flat(0.4)) == 700


def test_a_title_card_goes_from_its_logo_down():
    found = [_line("I STARTED AS THE WEAKEST", top=100), _line("Soka", top=400), _line("Leveling", top=450)]
    assert junk_from(found, TITLES, _flat(0.7)) == 400


def test_an_end_card_above_the_credits_goes_with_them():
    found = [
        _line("To Be Continued...", top=300),
        _line("Solo", top=400),
        _line("Leveling", top=450),
        _line("Translator: JJoelle", top=800),
        _line("Editor: Sami", top=850),
    ]
    assert junk_from(found, TITLES, _flat(0.8)) == 300


def test_inside_the_chapter_only_the_title_card_counts():
    credits = [_line("Translator: JJoelle"), _line("Editor: Sami")]
    assert junk_from(credits, TITLES, _flat(0.9), ends=False) is None
    assert junk_from([_line("To Be Continued...")], TITLES, _flat(0.9), ends=False) is None
    assert junk_from([_line("SOLO LEVELING")], TITLES, _flat(0.8), ends=False) == 500


def test_a_title_set_letter_by_letter_is_still_the_title_card():
    """ORV's logo runs down in three columns: OCR reads loose letters, in no order."""
    titles = ["Omniscient Reader's Viewpoint"]
    loose = [_line(c, top=100 + 10 * i) for i, c in enumerate("OMRNEVIAISDECEWRPESONITNT")]
    assert junk_from(loose + [_line("Art: SLEEPY-C")], titles, _flat(0.95), ends=False) == 100


def test_loose_letters_amid_other_words_are_not_the_title():
    titles = ["Omniscient Reader's Viewpoint"]
    words = [_line("OMNISCIENT READER, WHAT DO YOU SEE FROM UP THERE IN THE VIEWPOINT TOWER")]
    assert junk_from(words, titles, _flat(0.95), ends=False) is None


def test_to_be_continued_in_busy_art_is_still_the_story():
    assert junk_from([_line("TO BE CONTINUED")], TITLES, _flat(0.2)) is None


def test_how_empty_a_piece_is_counts_from_where_the_junk_starts():
    """Credits under a story panel: busy on top, but empty around the credits."""
    found = [_line("I MUST HAVE COURAGE", top=100), _line("TRANSLATED BY: SHOCKSWORD", top=800)]
    assert junk_from(found, TITLES, _flat(0.3)) == 800


def test_panel_junk_reads_the_piece_with_ocr_and_judges_it(tmp_path):
    path = tmp_path / "panel-001.png"
    Image.new("RGB", (20, 40), (255, 255, 255)).save(path)
    read = []

    def engine(image, use_cls):
        read.append(image)
        return [_line("Translator: JJoelle", top=10), _line("Editor: Sami", top=30)], 0.1

    assert PanelJunk(engine)(path, TITLES, _flat(0.9)) == 10
    assert read == [str(path)]


def test_panel_junk_treats_nothing_found_as_the_story(tmp_path):
    path = tmp_path / "panel-001.png"
    Image.new("RGB", (20, 40), (255, 255, 255)).save(path)
    assert PanelJunk(lambda image, use_cls: (None, 0.1))(path, TITLES, _flat(0.9)) is None


def test_lettering_gives_the_rows_of_each_line_the_detector_boxes():
    from manhwatok.adapters.lettering import Lettering

    def engine(image, use_det, use_cls, use_rec):
        assert (use_det, use_cls, use_rec) == (True, False, False)
        return [[[0, 10], [50, 12], [50, 30], [0, 28]]], 0.1

    assert Lettering(engine)(Image.new("RGB", (60, 60))) == [(10, 30)]
