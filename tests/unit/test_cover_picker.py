import numpy as np
import pytest
from PIL import Image, ImageDraw

from manhwatok.adapters import cover_picker
from manhwatok.adapters.cover_picker import (
    ClipPicker,
    PlainPicker,
    build_picker,
    clear_of_text,
    panels,
    pieces,
    pixels,
)
from manhwatok.ports.picker import Focus


def _drawn(seed=1):
    """A busy, colourful picture, like a drawn panel."""
    rng = np.random.default_rng(seed)
    noise = rng.integers(40, 200, (960, 540, 3), dtype=np.uint8)
    img = Image.fromarray(noise, "RGB")
    draw = ImageDraw.Draw(img)
    for _ in range(80):
        x, y = rng.integers(0, 540), rng.integers(0, 960)
        colour = tuple(int(c) for c in rng.integers(0, 255, 3))
        draw.ellipse((x, y, x + 60, y + 60), fill=colour)
    return img


def _whole(img):
    return (0, 0, img.width, img.height)


def test_the_plain_picker_puts_a_drawn_panel_over_black_and_blank_pages():
    black, white = Image.new("RGB", (540, 960)), Image.new("RGB", (540, 960), (255, 255, 255))
    drawn = _drawn()
    assert PlainPicker().focus([black, drawn, white])[0].index == 1


def test_nothing_to_pick_from_gives_no_focus():
    assert PlainPicker().focus([]) == []


def _page():
    """A white page with two drawn panels, one above the other, and a side-by-side pair."""
    page = Image.new("RGB", (1080, 1920), (255, 255, 255))
    page.paste(_drawn(1).resize((1000, 500)), (40, 60))
    page.paste(_drawn(2).resize((1000, 600)), (40, 700))
    page.paste(_drawn(3).resize((480, 400)), (40, 1450))
    page.paste(_drawn(4).resize((480, 400)), (560, 1450))
    return page


def _near(found, want, slack=12):
    return len(found) == len(want) and all(
        abs(a - b) <= slack for f, w in zip(found, want) for a, b in zip(f, w)
    )


def test_a_page_is_cut_into_its_panels_without_the_gutters():
    found = panels(_page())
    want = [(40, 60, 1040, 560), (40, 700, 1040, 1300), (40, 1450, 520, 1850), (560, 1450, 1040, 1850)]
    assert _near(found, want), found


def test_a_picture_without_gutters_is_one_panel():
    assert _near(panels(_drawn()), [(0, 0, 540, 960)])


def test_a_tall_panel_is_also_scored_in_windows():
    tall = _drawn()  # 540×960: taller than 1.4 widths
    found = pieces(tall)
    assert found[0][3] - found[0][1] > 900  # the whole panel
    assert len(found) > 2
    assert all(b - t < 700 for _, t, _, b in found[1:])  # then its windows


def test_clip_focuses_on_its_best_scoring_piece(tmp_path, monkeypatch):
    picker = ClipPicker(tmp_path, text=None)
    page = _page()

    def score(crops):  # the side-by-side pair's right-hand panel is the one it likes
        return [1.0 if c.size[0] < 520 and n == 3 else 0.0 for n, c in enumerate(crops)]

    monkeypatch.setattr(picker, "scores", score)
    (focus,) = picker.focus([page])
    assert focus.index == 0 and _near([focus.box], [(560, 1450, 1040, 1850)])


def test_a_piece_is_cut_clear_of_lettering_at_its_edge():
    """A system window across the top of a panel: the art below it is kept, the window cut."""
    box, covered = clear_of_text((0, 100, 1000, 1100), [(200, 20, 800, 120)])
    assert box == (0, 100 + 136, 1000, 1100) and covered == 0.0


def test_lettering_in_the_middle_of_a_piece_counts_against_it():
    box, covered = clear_of_text((0, 0, 1000, 1000), [(0, 300, 1000, 700)])
    assert box == (0, 0, 1000, 1000)
    assert covered == pytest.approx(0.4)


def test_a_piece_without_lettering_is_kept_whole():
    assert clear_of_text((5, 5, 500, 500), []) == ((5, 5, 500, 500), 0.0)


def test_clip_passes_over_a_piece_full_of_text_for_a_clean_one(tmp_path, monkeypatch):
    left, right = _drawn(1).resize((500, 500)), _drawn(2).resize((500, 500))
    wordy = lambda img: [(0, 150, img.width, 350)] if img.getpixel((0, 0)) == left.getpixel((0, 0)) else []
    picker = ClipPicker(tmp_path, text=wordy)
    monkeypatch.setattr(picker, "scores", lambda crops: [0.9, 0.7][: len(crops)] + [0.0] * (len(crops) - 2))
    assert picker.focus([left, right])[0].index == 1


def test_clip_falls_back_to_the_plain_measure_when_the_model_fails(tmp_path, monkeypatch):
    said = []
    picker = ClipPicker(tmp_path, said.append)

    def broken(images):
        raise OSError("no network")

    monkeypatch.setattr(picker, "scores", broken)
    black = Image.new("RGB", (540, 960))
    assert picker.focus([black, _drawn()])[0].index == 1
    assert picker.focus([black, _drawn()])[0].index == 1  # the model is not tried again
    assert len(said) == 1 and "no network" in said[0]


def test_one_piece_needs_no_model(tmp_path, monkeypatch):
    picker = ClipPicker(tmp_path)
    monkeypatch.setattr(picker, "scores", lambda images: pytest.fail("model was loaded"))
    small = _drawn().resize((540, 600))
    (focus,) = picker.focus([small])
    assert focus.index == 0 and _near([focus.box], [_whole(small)])


def test_several_foci_are_distinct_pieces_best_first(tmp_path, monkeypatch):
    picker = ClipPicker(tmp_path, text=None)
    page = _page()
    # Likes the lowest pieces best: the pair, then the middle panel, then the top one.
    monkeypatch.setattr(picker, "scores", lambda crops: [float(n) for n in range(len(crops))])
    found = picker.focus([page], 3)
    assert len(found) == 3
    tops = [f.box[1] for f in found]
    assert len(set(f.box for f in found)) == 3
    assert tops[0] >= tops[-1]


def test_clip_pixels_are_a_normalised_224_square_channels_first():
    data = pixels(Image.new("RGB", (1080, 1920), (255, 255, 255)))
    assert data.shape == (3, 224, 224)
    assert data.dtype == np.float32
    assert np.allclose(data[:, 0, 0], (1 - cover_picker.MEAN) / cover_picker.STD)


def test_without_the_pick_extra_the_plain_picker_stands_in(tmp_path, monkeypatch):
    monkeypatch.setattr(cover_picker.importlib.util, "find_spec", lambda name: None)
    assert isinstance(build_picker(tmp_path), PlainPicker)


def test_a_small_piece_loses_to_a_big_one_clip_likes_as_much(tmp_path, monkeypatch):
    """Blown up to a cover, a small piece goes soft."""
    page = Image.new("RGB", (1080, 1920), (255, 255, 255))
    page.paste(_drawn(1).resize((260, 260)), (40, 60))
    page.paste(_drawn(2).resize((1000, 900)), (40, 600))
    picker = ClipPicker(tmp_path, text=None)
    monkeypatch.setattr(picker, "scores", lambda crops: [1.0] * len(crops))
    (focus,) = picker.focus([page])
    assert focus.box[1] > 500  # the big panel
