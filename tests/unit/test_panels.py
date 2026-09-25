import pytest

from manhwatok.domain.panels import cut_rows, gutter_bands, is_blank, next_cut, squeeze

FLAT, INK = 1.0, 90.0


def _strip(*runs: tuple[float, int]) -> list[float]:
    """A strip described as (spread, how many rows) runs, e.g. (INK, 300), (FLAT, 40)."""
    return [value for value, rows in runs for _ in range(rows)]


# --- where the gutters are ------------------------------------------------------------------


def test_gutter_bands_finds_the_runs_of_flat_rows():
    spreads = _strip((INK, 10), (FLAT, 5), (INK, 3), (FLAT, 2))
    assert gutter_bands(spreads) == [(10, 15), (18, 20)]


def test_a_row_with_ink_is_never_a_gutter():
    """A speech bubble is ink: its rows span white fill and black lettering."""
    assert gutter_bands(_strip((INK, 20))) == []


def test_a_strip_that_is_all_gutter_is_one_band():
    assert gutter_bands(_strip((FLAT, 12))) == [(0, 12)]


# --- where to cut ----------------------------------------------------------------------------


def test_next_cut_is_none_while_the_strip_is_shorter_than_a_slide():
    """More pages may still arrive, so there is nothing to decide yet."""
    assert next_cut(_strip((INK, 900)), target=1000) is None


def test_next_cut_lands_in_the_gutter_nearest_a_full_slide():
    spreads = _strip((INK, 940), (FLAT, 40), (INK, 200))
    assert next_cut(spreads, target=1000, slack=200, min_piece=100) == 960  # the band's middle


def test_next_cut_prefers_the_widest_gutter_within_the_slack():
    spreads = _strip((INK, 840), (FLAT, 10), (INK, 50), (FLAT, 80), (INK, 200))
    assert next_cut(spreads, target=1000, slack=200, min_piece=100) == 940


def test_next_cut_falls_back_to_a_hard_cut_when_no_gutter_is_in_reach():
    """A full-bleed splash page has nowhere safe; a hard cut beats a 4000px slide."""
    assert next_cut(_strip((INK, 3000)), target=1000, slack=200, min_piece=100) == 1000


def test_next_cut_ignores_a_gutter_that_would_leave_too_short_a_piece():
    spreads = _strip((INK, 40), (FLAT, 30), (INK, 1500))
    assert next_cut(spreads, target=1000, slack=990, min_piece=500) == 1000


def test_next_cut_never_cuts_past_the_slide():
    spreads = _strip((INK, 1000), (FLAT, 200), (INK, 500))
    assert next_cut(spreads, target=1000, slack=200, min_piece=100) <= 1000


# --- cutting a whole strip --------------------------------------------------------------------


def test_cut_rows_never_falls_on_a_row_with_ink_when_a_gutter_is_in_reach():
    spreads = _strip((INK, 900), (FLAT, 60), (INK, 900), (FLAT, 60), (INK, 300))
    rows = cut_rows(spreads, target=1000, slack=200, min_piece=100)
    assert rows and all(spreads[row] < 10 for row in rows)


def test_cut_rows_pieces_are_never_taller_than_a_slide():
    spreads = _strip((INK, 900), (FLAT, 60), (INK, 2000))
    rows = cut_rows(spreads, target=1000, slack=200, min_piece=100)
    edges = [0, *rows, len(spreads)]
    assert all(b - a <= 1000 for a, b in zip(edges, edges[1:]))


def test_cut_rows_of_an_all_flat_strip_cuts_at_full_slides():
    rows = cut_rows(_strip((FLAT, 2500)), target=1000, slack=200, min_piece=100)
    assert rows == [1000, 2000]


def test_cut_rows_of_a_strip_shorter_than_a_slide_cuts_nowhere():
    assert cut_rows(_strip((INK, 400)), target=1000) == []


@pytest.mark.parametrize("target", [500, 1000, 1920])
def test_cut_rows_rise_and_stay_inside_the_strip(target):
    spreads = _strip((INK, 700), (FLAT, 40), (INK, 1200), (FLAT, 40), (INK, 900))
    rows = cut_rows(spreads, target=target, slack=200, min_piece=100)
    assert rows == sorted(set(rows))
    assert all(0 < row < len(spreads) for row in rows)


# --- keeping bubbles whole ---------------------------------------------------------------------


def test_next_cut_takes_the_lowest_real_gutter_so_slides_stay_full():
    spreads = _strip((INK, 500), (FLAT, 60), (INK, 300), (FLAT, 40), (INK, 400))
    assert next_cut(spreads, target=1000, slack=600, min_piece=100, min_gutter=20) == 880


def test_next_cut_reaches_far_above_a_full_slide_for_a_gutter_rather_than_cut_the_art():
    spreads = _strip((INK, 500), (FLAT, 40), (INK, 2000))
    assert next_cut(spreads, target=1000, slack=600, min_piece=100, min_gutter=20) == 520


def test_a_gap_too_thin_to_be_a_gutter_loses_to_a_real_one():
    """Between the lines of a bubble is flat, but it is not where panels end."""
    spreads = _strip((INK, 500), (FLAT, 40), (INK, 400), (FLAT, 6), (INK, 400))
    assert next_cut(spreads, target=1000, slack=600, min_piece=100, min_gutter=20) == 520


def test_protected_rows_are_never_a_gutter():
    spreads = _strip((INK, 500), (FLAT, 40), (INK, 400), (FLAT, 40), (INK, 400))
    protected = [900 <= row < 1000 for row in range(len(spreads))]
    cut = next_cut(spreads, target=1000, slack=600, min_piece=100, min_gutter=20, protected=protected)
    assert cut == 520


def test_with_no_gutter_the_slide_is_kept_full_rather_than_cut_short_and_padded():
    spreads = _strip((INK, 700), (30.0, 5), (INK, 2000))
    assert next_cut(spreads, target=1000, slack=600, min_piece=100, min_gutter=20) == 1000


def test_with_no_gutter_the_cut_never_goes_through_a_bubble():
    spreads = _strip((INK, 3000))
    protected = [800 <= row <= 1000 for row in range(len(spreads))]
    cut = next_cut(spreads, target=1000, slack=600, min_piece=100, min_gutter=20, protected=protected)
    assert cut == 799  # as full as the bubble allows


def test_among_equally_busy_rows_the_cut_keeps_the_slide_full():
    assert next_cut(_strip((INK, 3000)), target=1000, slack=600, min_piece=100) == 1000


# --- squeezing long gaps and dropping blank pieces -----------------------------------------------


def test_squeeze_shortens_a_long_gap_to_the_limit_keeping_both_edges():
    spreads = _strip((INK, 100), (FLAT, 500), (INK, 100))
    kept = squeeze(spreads, max_gap=100)
    assert kept == [(0, 150), (550, 700)]
    assert sum(b - a for a, b in kept) == 300


def test_squeeze_leaves_a_normal_gutter_alone():
    spreads = _strip((INK, 100), (FLAT, 80), (INK, 100))
    assert squeeze(spreads, max_gap=100) == [(0, 280)]


def test_squeeze_leaves_a_gap_still_running_off_the_bottom_until_it_ends():
    """The next page may carry on the same gap; it is squeezed once it is whole."""
    spreads = _strip((INK, 100), (FLAT, 500))
    assert squeeze(spreads, max_gap=100) == [(0, 600)]
    assert squeeze(spreads, max_gap=100, ended=True) == [(0, 150), (550, 600)]


def test_a_piece_that_is_all_margin_is_blank_and_one_with_art_is_not():
    assert is_blank(_strip((FLAT, 1000)))
    assert is_blank(_strip((FLAT, 990), (INK, 10)))
    assert not is_blank(_strip((FLAT, 800), (INK, 200)))
    assert not is_blank([])
