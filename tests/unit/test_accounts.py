import pytest

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.accounts import add_account, add_theme, update_account, update_theme
from manhwatok.app.names import AniListNames
from manhwatok.domain.errors import (
    AccountNotFound,
    AlreadyExists,
    InvalidName,
    ManhwatokError,
    ThemeNotFound,
)
from manhwatok.domain.models import Sort, TagInfo
from manhwatok.domain.post import DEFAULT_HASHTAGS
from tests.unit.fakes import FakeMetadata


class Meta(FakeMetadata):
    def __init__(self):
        super().__init__(
            tags=[TagInfo(name="Harem", category="Theme"), TagInfo(name="Revenge", category="T")],
            genres=["Action", "Fantasy", "Romance"],
        )
        self.lookups = 0

    def list_genres(self):
        self.lookups += 1
        return super().list_genres()

    def list_tags(self):
        self.lookups += 1
        return super().list_tags()


@pytest.fixture
def env(tmp_path):
    meta = Meta()
    with SqliteStore(tmp_path / "m.db") as store:
        yield store, AniListNames(meta, store.cache, print), meta


def test_add_account_uses_defaults_and_anilist_spelling(env):
    store, names, _ = env
    account = add_account(
        store.accounts,
        names,
        "@Reads",
        {"genres": ["action", "fantasy"], "block_tags": ["harem"]},
    )
    assert account.handle == "reads"
    assert account.genres == ["Action", "Fantasy"]
    assert account.block_tags == ["Harem"]
    assert account.hashtags == DEFAULT_HASHTAGS
    assert store.accounts.get("reads") == account


def test_add_existing_account_fails(env):
    store, names, _ = env
    add_account(store.accounts, names, "reads", {})
    with pytest.raises(AlreadyExists):
        add_account(store.accounts, names, "@READS", {})


def test_bad_handle_fails_before_any_lookup(env):
    store, names, meta = env
    with pytest.raises(InvalidName):
        add_account(store.accounts, names, "no spaces", {"genres": ["Action"]})
    assert meta.lookups == 0


def test_unknown_genre_is_rejected_and_nothing_saved(env):
    store, names, _ = env
    with pytest.raises(InvalidName, match="did you mean Romance"):
        add_account(store.accounts, names, "reads", {"block_genres": ["Romanse"]})
    assert store.accounts.list() == []


def test_update_changes_only_given_fields(env):
    store, names, meta = env
    add_account(store.accounts, names, "reads", {"genres": ["Action"], "repeat_days": 7})
    lookups = meta.lookups
    updated = update_account(store.accounts, names, "@reads", {"hashtags": "#x"})
    assert updated.hashtags == "#x"
    assert updated.genres == ["Action"]
    assert updated.repeat_days == 7
    assert meta.lookups == lookups  # no list given, nothing to look up
    assert store.accounts.get("reads") == updated


def test_update_can_clear_a_list(env):
    store, names, _ = env
    add_account(store.accounts, names, "reads", {"genres": ["Action"]})
    assert update_account(store.accounts, names, "reads", {"genres": []}).genres == []


def test_update_missing_account(env):
    store, names, _ = env
    with pytest.raises(AccountNotFound, match="no account @ghost"):
        update_account(store.accounts, names, "ghost", {"hashtags": "#x"})


def test_update_without_changes_fails(env):
    store, names, _ = env
    add_account(store.accounts, names, "reads", {})
    with pytest.raises(ManhwatokError, match="nothing to change"):
        update_account(store.accounts, names, "reads", {})


def test_add_theme_checks_names(env):
    store, names, _ = env
    theme = add_theme(
        store.themes,
        names,
        name="Revenge",
        tags=["revenge"],
        genres=["action"],
        sort=Sort.POPULARITY,
        min_tag_rank=70,
        title="MC gets *revenge*",
    )
    assert (theme.name, theme.tags, theme.genres) == ("revenge", ["Revenge"], ["Action"])
    assert store.themes.get("revenge") == theme
    with pytest.raises(AlreadyExists, match="theme revenge already exists"):
        add_theme(store.themes, names, "revenge", ["Revenge"], [], Sort.SCORE, 60, "t")


def test_add_theme_validates_before_lookup(env):
    store, names, meta = env
    with pytest.raises(InvalidName):
        add_theme(store.themes, names, "bad name", ["Revenge"], [], Sort.SCORE, 60, "t")
    assert meta.lookups == 0


def test_update_theme_changes_only_the_given_fields_and_checks_new_names(env):
    store, names, meta = env
    add_theme(store.themes, names, "revenge", ["revenge"], [], Sort.SCORE, 60, "t")
    lookups = meta.lookups
    theme = update_theme(store.themes, names, "Revenge", {"title": "New", "sort": Sort.TRENDING})
    assert (theme.title, theme.sort, theme.tags) == ("New", Sort.TRENDING, ["Revenge"])
    assert meta.lookups == lookups  # names unchanged: not looked up again
    theme = update_theme(store.themes, names, "revenge", {"genres": ["action"]})
    assert theme.genres == ["Action"]
    assert store.themes.get("revenge") == theme


def test_update_theme_errors(env):
    store, names, _ = env
    with pytest.raises(ThemeNotFound):
        update_theme(store.themes, names, "ghost", {"title": "x"})
    add_theme(store.themes, names, "revenge", ["Revenge"], [], Sort.SCORE, 60, "t")
    with pytest.raises(ManhwatokError, match="give at least one tag or genre"):
        update_theme(store.themes, names, "revenge", {"tags": []})
    with pytest.raises(InvalidName, match="did you mean Harem"):
        update_theme(store.themes, names, "revenge", {"tags": ["Harm"]})
    assert store.themes.get("revenge").tags == ["Revenge"]
