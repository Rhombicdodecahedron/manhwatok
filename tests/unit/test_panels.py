import pytest

from manhwatok.domain.panels import cut_rows, gutter_bands, next_cut

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
