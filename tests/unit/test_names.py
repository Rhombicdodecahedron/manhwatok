import pytest

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.names import AniListNames, canonical_names
from manhwatok.domain.errors import CacheError, InvalidName, MetadataError
from manhwatok.domain.models import TagInfo
from tests.unit.fakes import Clock, FakeMetadata

GENRES = ["Action", "Drama", "Fantasy", "Romance", "Slice of Life"]
TAGS = [TagInfo(name=n, category="Theme") for n in ("Revenge", "Time Manipulation", "Harem")]


class CountingMetadata(FakeMetadata):
    def __init__(self, error: Exception | None = None):
        super().__init__(tags=TAGS, genres=GENRES)
        self.error = error
        self.fetches: list[str] = []

    def list_genres(self):
        self.fetches.append("genres")
        if self.error:
            raise self.error
        return super().list_genres()

    def list_tags(self):
        self.fetches.append("tags")
        if self.error:
            raise self.error
        return super().list_tags()


class BrokenCache:
    def get(self, key, max_age):
        raise CacheError("locked")

    def put(self, key, value):
        raise CacheError("locked")


def test_canonical_names_fix_case_and_dedupe():
    assert canonical_names(["action", "ACTION", "slice of life"], GENRES, "genre") == [
        "Action",
        "Slice of Life",
    ]


def test_unknown_name_suggests_close_matches():
    with pytest.raises(InvalidName, match=r"unknown genre 'Actoin' — did you mean Action\?"):
        canonical_names(["Actoin"], GENRES, "genre")


def test_unknown_genre_without_close_match_lists_all_genres():
    with pytest.raises(InvalidName, match="AniList genres: Action, Drama, Fantasy"):
        canonical_names(["Zzz"], GENRES, "genre")


def test_unknown_tag_without_close_match_points_to_tags_command():
    with pytest.raises(InvalidName, match="see `manhwatok tags`"):
        canonical_names(["Zzz"], ["Revenge"], "tag")


def test_lists_are_fetched_once_and_cached(tmp_path):
    meta = CountingMetadata()
    store = SqliteStore(tmp_path / "m.db")
    assert AniListNames(meta, store.cache, print).genres(["romance"]) == ["Romance"]
    assert AniListNames(meta, store.cache, print).genres(["drama"]) == ["Drama"]
    assert AniListNames(meta, store.cache, print).tags(["revenge"]) == ["Revenge"]
    assert meta.fetches == ["genres", "tags"]


def test_cached_lists_expire_after_a_day(tmp_path):
    meta = CountingMetadata()
    clock = Clock()
    cache = SqliteStore(tmp_path / "m.db", clock=clock).cache
    AniListNames(meta, cache, print).genres(["Action"])
    clock.now += 24 * 3600 + 1
    AniListNames(meta, cache, print).genres(["Action"])
    assert meta.fetches == ["genres", "genres"]


def test_empty_list_needs_no_lookup(tmp_path):
    meta = CountingMetadata()
    assert AniListNames(meta, SqliteStore(tmp_path / "m.db").cache, print).genres([]) == []
    assert meta.fetches == []


def test_anilist_down_warns_once_and_keeps_names_as_typed(tmp_path):
    meta = CountingMetadata(error=MetadataError("AniList unreachable: boom"))
    warnings = []
    names = AniListNames(meta, SqliteStore(tmp_path / "m.db").cache, warnings.append)
    assert names.genres(["Actoin"]) == ["Actoin"]
    assert names.tags(["revenge"]) == ["revenge"]
    assert meta.fetches == ["genres"]  # no second attempt once AniList is known to be down
    assert warnings == [
        "warning: couldn't check names against AniList (AniList unreachable: boom) — saved as typed"
    ]


def test_broken_cache_still_checks_names():
    meta = CountingMetadata()
    assert AniListNames(meta, BrokenCache(), print).genres(["action"]) == ["Action"]


@pytest.mark.parametrize("corrupt", ["not json", '{"Action": 1}', '"Action"', "[1, 2]"])
def test_corrupt_cached_list_is_a_miss_and_gets_overwritten(tmp_path, corrupt):
    meta = CountingMetadata()
    with SqliteStore(tmp_path / "m.db") as store:
        AniListNames(meta, store.cache, print).genres(["action"])
        store.write(CacheError, "UPDATE cache SET value = ?", (corrupt,))
        assert AniListNames(meta, store.cache, print).genres(["action"]) == ["Action"]
        assert AniListNames(meta, store.cache, print).genres(["drama"]) == ["Drama"]
    assert meta.fetches == ["genres", "genres"]
