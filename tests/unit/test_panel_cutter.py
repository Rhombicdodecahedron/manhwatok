import json

import numpy as np
import pytest
from PIL import Image, ImageDraw

from manhwatok.adapters.panel_cutter import PANELS_FILE, PillowPanelCutter
from manhwatok.domain.errors import MetadataError, StorageError

WHITE, INK = (255, 255, 255), (20, 20, 30)


def _cutter(**fields):
    """A cutter at toy size: a whole webtoon fits in a few hundred bytes."""
    return PillowPanelCutter(
        **{
            "width": 20,
            "height": 40,
            "slack": 12,
            "min_piece": 8,
            "min_gutter": 2,
            "max_gap": 10_000,
            **fields,
        }
    )


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


# --- bubbles, empty stretches and pages that are not the story ---------------------------------


def _art_with_a_bubble(tmp_path, bubble_top=350):
    """200px-wide full-bleed art (stripes: no row is flat, so there is no gutter anywhere) with
    a lettered white bubble straddling where a 400px slide would end."""
    img = Image.new("RGB", (200, 1200), (40, 40, 40))
    draw = ImageDraw.Draw(img)
    for x in range(0, 200, 20):
        draw.rectangle((x, 0, x + 9, 1199), fill=(120, 110, 100))
    draw.ellipse((40, bubble_top, 160, bubble_top + 100), fill=WHITE, outline=INK, width=3)
    for line in range(3):
        top = bubble_top + 30 + line * 16
        draw.rectangle((70, top, 130, top + 7), fill=INK)
    path = tmp_path / "art.png"
    img.save(path)
    return path


def _bubble_cutter(**fields):
    return PillowPanelCutter(
        **{
            "width": 200,
            "height": 400,
            "slack": 200,
            "min_piece": 50,
            "min_gutter": 10,
            "lookahead": 100,
            **fields,
        }
    )


def _white_run(path, x=100):
    with Image.open(path) as img:
        pixels = img.convert("L").load()
        return sum(pixels[x, y] > 240 for y in range(img.height))


def test_bubble_rows_marks_the_rows_a_lettered_bubble_spans(tmp_path):
    with Image.open(_art_with_a_bubble(tmp_path)) as img:
        rows = _bubble_cutter().bubble_rows(img.convert("RGB"))
    assert all(rows[360:440])
    assert not any(rows[:300]) and not any(rows[500:])


def test_a_bubble_where_a_slide_would_end_is_kept_whole_in_the_next_slide(tmp_path):
    first, second, *_ = _bubble_cutter().cut([_art_with_a_bubble(tmp_path)], tmp_path / "out")
    assert _white_run(first) == 0
    assert _white_run(second) >= 65  # the whole bubble, less its lettering


def test_a_long_empty_stretch_is_squeezed(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 20), (WHITE, 300), (INK, 20)])
    [panel] = _cutter(height=100, slack=50, max_gap=10).cut([page], tmp_path / "out")
    assert _rows(panel)[:50] == ["ink"] * 20 + ["blank"] * 10 + ["ink"] * 20


def test_a_blank_stretch_never_becomes_a_slide(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 34), (WHITE, 206), (INK, 34), (WHITE, 6)])
    panels = _cutter().cut([page], tmp_path / "out")
    assert [p.name for p in panels] == ["panel-001.png", "panel-002.png"]
    assert all(_rows(p)[0] == "ink" for p in panels)


def test_junk_at_either_end_is_dropped_and_the_rest_renumbered(tmp_path):
    bands = [(INK, 34), (WHITE, 6)] * 5
    page = _page(tmp_path, "p1.png", bands)
    asked = []

    def junk(path, titles, margin, ends):
        asked.append((path.name, tuple(titles)))
        return 0  # junk from the top: nothing of it is the story

    out = tmp_path / "out"
    panels = _cutter(junk=junk, junk_scan=1, title_scan=0).cut([page], out, titles=["Solo Leveling"])
    assert [p.name for p in panels] == ["panel-001.png", "panel-002.png", "panel-003.png"]
    assert sorted(p.name for p in out.glob("panel-*")) == [p.name for p in panels]
    assert asked == [("panel-001.png", ("Solo Leveling",)), ("panel-005.png", ("Solo Leveling",))]


def test_inside_the_chapter_only_a_whole_title_card_is_dropped_never_a_part(tmp_path):
    bands = [(INK, 34), (WHITE, 6)] * 5
    page = _page(tmp_path, "p1.png", bands)
    seen = []

    def junk(path, titles, margin, ends):
        seen.append((path.name, ends))
        return {"panel-002.png": 0, "panel-003.png": 20}.get(path.name)

    out = tmp_path / "out"
    panels = _cutter(junk=junk, junk_scan=1, title_scan=4).cut([page], out)
    assert len(panels) == 4  # 002 dropped whole; 003 kept whole, not cut back
    assert _rows(panels[1]).count("ink") == 34
    assert seen == [
        ("panel-001.png", True),
        ("panel-002.png", False),
        ("panel-003.png", False),
        ("panel-004.png", False),
        ("panel-005.png", True),
    ]


def test_credits_sharing_a_slide_with_the_story_are_trimmed_off_at_the_gutter_above(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 14), (WHITE, 6), (INK, 4), (WHITE, 16)])
    [panel] = _cutter(junk=lambda path, titles, margin, ends: 20).cut([page], tmp_path / "out")
    assert _rows(panel) == ["ink"] * 14 + ["blank"] * 26


def test_junk_with_no_gutter_above_it_takes_the_whole_slide(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 30), (WHITE, 10)])
    assert _cutter(junk=lambda path, titles, margin, ends: 20).cut([page], tmp_path / "out") == []


def test_a_junk_check_is_told_how_much_of_each_row_is_margin(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 4), (WHITE, 36), (INK, 34), (WHITE, 6)])
    seen = []
    _cutter(junk=lambda path, titles, margin, ends: seen.append(margin) and None).cut(
        [page], tmp_path / "out"
    )
    assert all(share == pytest.approx(0.2) for share in seen[0][:4])  # the ink's side margins
    assert all(share == 1.0 for share in seen[0][4:])
    assert all(share < 0.5 for share in seen[1][:34])


def test_a_folder_cut_by_an_older_cutter_is_cut_again(tmp_path):
    page = _page(tmp_path, "p1.png", [(INK, 34), (WHITE, 6), (INK, 20)])
    out = tmp_path / "out"
    panels = _cutter().cut([page], out)
    (out / PANELS_FILE).write_text(json.dumps([p.name for p in panels]))  # the old format
    (out / "panel-009.png").write_bytes(b"left over")
    assert _cutter().cut([page], out) == panels
    assert not (out / "panel-009.png").exists()
    assert json.loads((out / PANELS_FILE).read_text())["panels"] == [p.name for p in panels]


def _red(img):
    """Which rows of a picture have pure red (the fake lettering) on them."""
    pixels = np.asarray(img.convert("RGB"))
    return ((pixels == (255, 0, 0)).all(axis=2)).any(axis=1)


def _red_rows(img):
    """A fake lettering check: the red rows, as one line."""
    rows = np.flatnonzero(_red(img))
    return [(int(rows[0]), int(rows[-1]))] if rows.size else []


def _art_with_lettering(tmp_path, top=390):
    """Full-bleed art (no gutter, no bubble shape) with a line of 'lettering' in pure red."""
    img = Image.new("RGB", (200, 1200), (40, 40, 40))
    draw = ImageDraw.Draw(img)
    for x in range(0, 200, 20):
        draw.rectangle((x, 0, x + 9, 1199), fill=(120, 110, 100))
    draw.rectangle((60, top, 140, top + 20), fill=(255, 0, 0))
    path = tmp_path / "art.png"
    img.save(path)
    return path


def _has_red(path):
    with Image.open(path) as img:
        return bool(_red(img).any())


def test_with_no_gutter_a_slide_stays_full_and_is_not_padded(tmp_path):
    first, *_ = _bubble_cutter().cut([_art_with_lettering(tmp_path, top=1000)], tmp_path / "out")
    with Image.open(first) as img:
        assert img.convert("L").getpixel((5, 399)) == img.convert("L").getpixel((5, 0))  # art


def test_lettering_where_a_slide_would_end_is_never_cut(tmp_path):
    first, second, *_ = _bubble_cutter(lettering=_red_rows).cut(
        [_art_with_lettering(tmp_path)], tmp_path / "out"
    )
    assert not _has_red(first) and _has_red(second)


def test_without_a_lettering_check_the_same_line_is_sliced(tmp_path):
    first, second, *_ = _bubble_cutter().cut([_art_with_lettering(tmp_path)], tmp_path / "out")
    assert _has_red(first) and _has_red(second)
