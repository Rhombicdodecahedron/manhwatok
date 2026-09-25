import numpy as np
from PIL import Image, ImageDraw

from manhwatok.adapters.watermark import Watermarks, paint_out

GREY, BADGE = (150, 160, 170), (108, 116, 124)


def _box(left, top, right, bottom):
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def _slide_with_badge():
    """Grey art with a flat badge at (100, 200)-(300, 260), words on it at (140, 215)-(290, 245)."""
    img = Image.new("RGB", (400, 400), GREY)
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 200, 300, 260), fill=BADGE)
    draw.rectangle((70, 210, 100, 250), fill=(80, 40, 120))  # the site's icon, beside it
    for x in range(140, 290, 16):  # the words: letters with the badge between them
        draw.rectangle((x, 218, x + 7, 242), fill=(170, 130, 230))
    return img


def _read_at_half(*found):
    """A fake OCR that reads a copy half the size: boxes come back halved."""
    halved = [([[x / 2, y / 2] for x, y in box], text, score) for box, text, score in found]
    return lambda pixels, use_cls: (halved, 0.1)


def test_a_website_mark_and_its_badge_are_painted_out():
    img = _slide_with_badge()
    found = [(_box(140, 215, 290, 245), "ASURASCANS.COM", 0.94)]
    clean = np.asarray(Watermarks(_read_at_half(*found))(img)).astype(int)
    patch = clean[195:265, 65:305]
    assert np.abs(patch.mean(axis=(0, 1)) - GREY).max() < 12  # the art's colour, icon and all


def test_a_slide_with_only_the_story_on_it_is_left_alone():
    found = [(_box(10, 10, 200, 40), "WHAT HAPPENED TO HIM.", 0.97)]
    assert Watermarks(lambda pixels, use_cls: (found, 0.1))(_slide_with_badge()) is None


def test_a_mark_read_without_confidence_is_left_alone():
    found = [(_box(140, 215, 290, 245), "ASURASCANS.COM", 0.3)]
    assert Watermarks(lambda pixels, use_cls: (found, 0.1))(_slide_with_badge()) is None


def test_words_on_a_colour_that_runs_on_are_painted_out_alone_not_the_whole_run():
    """A mark over the page's white margin: the margin is not a badge."""
    img = Image.new("RGB", (400, 400), (250, 250, 250))
    ImageDraw.Draw(img).rectangle((0, 0, 399, 150), fill=(30, 40, 60))  # dark art above
    for x in range(140, 290, 16):
        ImageDraw.Draw(img).rectangle((x, 218, x + 7, 242), fill=(170, 130, 230))
    clean = Watermarks(_read_at_half((_box(140, 215, 290, 245), "ASURASCANS.COM", 0.94)))(img)
    before, after = np.asarray(img), np.asarray(clean)
    changed = np.argwhere((before != after).any(axis=2))
    assert changed[:, 0].min() > 150 and changed[:, 1].min() > 100  # the art is untouched


def test_painting_out_touches_nothing_outside_the_boxes():
    pixels = np.asarray(_slide_with_badge())
    out = paint_out(pixels, [(100, 200, 300, 260)])
    assert (out[:190] == pixels[:190]).all() and (out[270:] == pixels[270:]).all()
