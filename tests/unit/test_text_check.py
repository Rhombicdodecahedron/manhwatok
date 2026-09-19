import pytest
from PIL import Image

from manhwatok.adapters.text_check import TextCheck, covers_text

W, H = 1000, 2000


def _word(text, score, area_pct):
    """An OCR result: a square box covering `area_pct` % of a WxH picture."""
    side = (area_pct / 100 * W * H) ** 0.5
    return ([[0, 0], [side, 0], [side, side], [0, side]], text, score)


@pytest.mark.parametrize(
    "found",
    [
        [_word("ARISE.", 0.97, 0.92)],  # a speech bubble
        [_word("THERE ARE SO MANY", 0.98, 1.2), _word("PEOPLE TO KILL.", 0.95, 1.05)],
        [_word("He's got the colour", 0.99, 15.65)],  # a meme caption
        [_word("CXACK", 0.56, 22.96)],  # a big sound effect, read with little confidence
        [_word("TikToK", 0.79, 0.6), _word("THE HOLES OF MY SW", 0.95, 3.27)],
    ],
)
def test_pictures_with_words_on_them_have_text(found):
    assert covers_text(found, W, H)


@pytest.mark.parametrize(
    "found",
    [
        [],
        [_word("@otakuwallz", 0.97, 0.63)],  # an artist's handle
        [_word("SOLOLEVELING", 0.99, 0.25)],  # a small logo in a corner
        [_word("S", 0.87, 2.69), _word("2", 0.5, 0.01)],  # single marks in the art
        [_word("AP", 0.7, 1.14)],  # texture misread as letters
    ],
)
def test_clean_pictures_have_none(found):
    assert not covers_text(found, W, H)


def test_the_check_reads_the_picture_once_with_its_engine(tmp_path):
    path = tmp_path / "a.jpg"
    Image.new("RGB", (W, H)).save(path)
    calls = []

    def engine(p, use_cls):
        calls.append(p)
        return [_word("MARRY ME!", 0.99, 1.54)], None

    assert TextCheck(engine=engine)(path) is True
    assert calls == [str(path)]


def test_an_unreadable_picture_counts_as_clean(tmp_path):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"nope")
    assert TextCheck(engine=lambda p, use_cls: ([], None))(path) is False
