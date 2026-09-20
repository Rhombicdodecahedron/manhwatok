import pytest

from manhwatok.domain.errors import InvalidName, ManhwatokError
from manhwatok.domain.models import SearchQuery, Sort
from manhwatok.domain.theme import Theme, normalize_theme_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("regression-revenge", "regression-revenge"), (" Murim ", "murim"), ("7-day", "7-day")],
)
def test_normalize_theme_name(raw, expected):
    assert normalize_theme_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "-lead", "under_score", "two words", "x" * 41])
def test_bad_theme_names(raw):
    with pytest.raises(InvalidName, match="not a theme name"):
        normalize_theme_name(raw)


def test_defaults_and_query():
    t = Theme(name="revenge", tags=["Revenge"], title="MC gets *revenge*")
    assert (t.genres, t.sort, t.min_tag_rank) == ([], Sort.SCORE, 60)
    assert t.to_query(8) == SearchQuery(tags=["Revenge"], limit=8)


def test_query_carries_every_filter():
    t = Theme(
        name="murim",
        tags=["Martial Arts"],
        genres=["Action"],
        sort=Sort.POPULARITY,
        min_tag_rank=80,
        title="t",
    )
    q = t.to_query(5)
    assert (q.tags, q.genres, q.sort, q.min_tag_rank, q.limit) == (
        ["Martial Arts"],
        ["Action"],
        Sort.POPULARITY,
        80,
        5,
    )


def test_needs_a_tag_or_genre():
    with pytest.raises(ManhwatokError, match="at least one tag or genre"):
        Theme(name="empty", title="t")


def test_needs_a_title():
    with pytest.raises(ManhwatokError, match="needs a title"):
        Theme(name="x1", tags=["Revenge"], title="   ")


@pytest.mark.parametrize("rank", [-1, 101])
def test_min_tag_rank_bounds(rank):
    with pytest.raises(ManhwatokError, match="min tag rank must be 0–100"):
        Theme(name="x1", tags=["Revenge"], title="t", min_tag_rank=rank)


def test_name_is_normalized_and_lists_cleaned():
    t = Theme(name="Revenge", tags=["Revenge", " Revenge "], title="t")
    assert t.name == "revenge"
    assert t.tags == ["Revenge"]


def test_json_round_trip():
    t = Theme(name="murim", genres=["Action"], sort=Sort.TRENDING, title="Best *murim*")
    assert Theme.model_validate_json(t.model_dump_json()) == t


def test_a_theme_keeps_its_sounds_tidy():
    theme = Theme(
        name="murim",
        tags=["Martial Arts"],
        title="T",
        sounds=["  Close Eyes DVRST ", "Close Eyes DVRST", "", "Sahara Hensonn"],
    )
    assert theme.sounds == ["Close Eyes DVRST", "Sahara Hensonn"]


def test_a_theme_without_sounds_has_none():
    assert Theme(name="murim", tags=["Martial Arts"], title="T").sounds == []
