import pytest
from PIL import Image, ImageDraw

from manhwatok.adapters.panel_cutter import PANELS_FILE, PillowPanelCutter
from manhwatok.domain.errors import MetadataError, StorageError

WHITE, INK = (255, 255, 255), (20, 20, 30)


def _cutter(**fields):
    """A cutter at toy size: a whole webtoon fits in a few hundred bytes."""
    return PillowPanelCutter(**{"width": 20, "height": 40, "slack": 12, "min_piece": 8, **fields})


def _page(tmp_path, name, bands, width=20):
    """A page built from (colour, rows) bands, e.g. [(INK, 30), (WHITE, 6)]."""
    height = sum(rows for _, rows in bands)
    img = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(img)
    at = 0
    for colour, rows in bands:
        if colour != WHITE:
            draw.rectangle((2, at, width - 3, at + rows - 1), fill=colour)
        at += rows
    path = tmp_path / name
    img.save(path)
    return path


def _rows(path):
    """Each row of a panel as 'ink' or 'blank', for asserting where a cut landed."""
    with Image.open(path) as img:
        pixels = img.convert("L").load()
        return [
            "ink" if min(pixels[x, y] for x in range(img.width)) < 200 else "blank"
            for y in range(img.height)
        ]


def test_row_spreads_are_flat_across_a_blank_band_and_high_across_a_drawing():
    img = Image.new("RGB", (20, 4), WHITE)
    ImageDraw.Draw(img).rectangle((2, 2, 17, 3), fill=INK)
    spreads = _cutter().row_spreads(img)
    assert spreads[0] < 6 and spreads[2] > 100


def test_cuts_a_strip_at_its_gutters_and_writes_them_in_reading_order(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 34), (WHITE, 6), (INK, 34), (WHITE, 6)])
    panels = _cutter().cut([page], tmp_path / "out")
    assert [p.name for p in panels] == ["panel-001.png", "panel-002.png"]
    assert all(row == "blank" for row in _rows(panels[0])[36:])  # cut inside the gutter


def test_pages_are_joined_in_page_order_so_reading_order_is_kept(tmp_path):
    first = _page(tmp_path, "p1.png", [(INK, 20), (WHITE, 20)])
    second = _page(tmp_path, "p2.png", [(WHITE, 20), (INK, 20)])
    [one, two] = _cutter().cut([first, second], tmp_path / "out")
    assert _rows(one)[0] == "ink" and _rows(one)[-1] == "blank"
    assert _rows(two)[0] == "blank" and _rows(two)[-1] == "ink"


def test_a_page_wider_or_narrower_than_the_slide_is_scaled_to_the_slide_width(tmp_path):
    wide = _page(tmp_path, "wide.png", [(INK, 30), (WHITE, 10)], width=60)
    [panel] = _cutter().cut([wide], tmp_path / "out")
    with Image.open(panel) as img:
        assert img.size == (20, 40)


def test_a_short_last_piece_is_padded_to_a_full_slide(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 34), (WHITE, 6), (INK, 10)])
    panels = _cutter().cut([page], tmp_path / "out")
    with Image.open(panels[-1]) as img:
        assert img.size == (20, 40)


def test_padding_uses_the_strips_own_background_not_black(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 34), (WHITE, 6), (INK, 10)])
    panels = _cutter().cut([page], tmp_path / "out")
    with Image.open(panels[-1]) as img:
        assert img.convert("RGB").getpixel((0, 39)) == WHITE


def test_a_speech_bubble_is_never_sliced_when_a_gutter_is_in_reach(tmp_path):
    """The bubble sits where a full slide would end; the cut belongs above it."""
    page = _page(tmp_path, "p1.png", [(INK, 30), (WHITE, 5), (INK, 20), (WHITE, 5)])
    panels = _cutter().cut([page], tmp_path / "out")
    assert _rows(panels[0])[30:35] == ["blank"] * 5


def test_a_page_tall_panel_with_no_gutter_is_cut_at_a_full_slide(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 100)])
    panels = _cutter().cut([page], tmp_path / "out")
    assert len(panels) == 3
    with Image.open(panels[0]) as img:
        assert img.height == 40


def test_every_panel_is_written_at_slide_size(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 34), (WHITE, 6), (INK, 34), (WHITE, 6), (INK, 12)])
    for panel in _cutter().cut([page], tmp_path / "out"):
        with Image.open(panel) as img:
            assert img.size == (20, 40)


def test_already_cut_panels_are_reused_instead_of_cutting_again(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 34), (WHITE, 6), (INK, 20)])
    out = tmp_path / "out"
    first = _cutter().cut([page], out)
    stamps = [p.stat().st_mtime_ns for p in first]
    again = _cutter().cut([page], out)
    assert again == first
    assert [p.stat().st_mtime_ns for p in again] == stamps


def test_a_half_written_panel_folder_is_cut_again(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 34), (WHITE, 6), (INK, 20)])
    out = tmp_path / "out"
    panels = _cutter().cut([page], out)
    panels[-1].unlink()
    assert _cutter().cut([page], out) == panels


def test_a_folder_with_no_manifest_is_cut_again(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 34), (WHITE, 6), (INK, 20)])
    out = tmp_path / "out"
    panels = _cutter().cut([page], out)
    (out / PANELS_FILE).unlink()
    assert _cutter().cut([page], out) == panels


def test_an_unreadable_page_is_a_metadata_error_naming_the_file(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a picture")
    with pytest.raises(MetadataError, match="broken.png"):
        _cutter().cut([broken], tmp_path / "out")


def test_cutting_into_a_blocked_folder_raises_storage_error(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 34), (WHITE, 6)])
    blocked = tmp_path / "out"
    blocked.write_text("in the way")
    with pytest.raises(StorageError):
        _cutter().cut([page], blocked)


def test_cutting_nothing_is_nothing(tmp_path):
    assert _cutter().cut([], tmp_path / "out") == []
