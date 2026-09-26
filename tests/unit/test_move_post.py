import pytest

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.move_post import move_post
from manhwatok.domain.account import Account
from manhwatok.domain.errors import AccountNotFound, ManhwatokError
from tests.unit.fakes import chapter_post, make_tools, post


@pytest.fixture
def world(tmp_path):
    tools = make_tools(tmp_path)
    with SqliteStore(tmp_path / "m.db") as store:
        store.accounts.add(Account(handle="old", byline="OLD STUDIO"))
        store.accounts.add(Account(handle="new", byline="NEW STUDIO"))
        store.accounts.add(Account(handle="plain"))
        yield tools, store


def test_moving_changes_the_account_and_its_own_byline(world):
    tools, store = world
    tools.posts.save(post(id="20260926-0001", account="old", byline="OLD STUDIO"))
    moved = move_post("20260926-0001", "@New", store.accounts, tools.posts)
    assert (moved.account, moved.byline) == ("new", "NEW STUDIO")
    assert tools.posts.get("20260926-0001") == moved


def test_a_byline_of_the_posts_own_is_kept(world):
    tools, store = world
    tools.posts.save(post(id="20260926-0001", account="old", byline="Custom"))
    assert move_post("20260926-0001", "plain", store.accounts, tools.posts).byline == "Custom"


def test_an_unknown_account_or_a_chapter_post_is_refused(world):
    tools, store = world
    tools.posts.save(post(id="20260926-0001", account="old"))
    tools.posts.save(chapter_post(id="20260926-0002", account="old"))
    with pytest.raises(AccountNotFound):
        move_post("20260926-0001", "nobody", store.accounts, tools.posts)
    with pytest.raises(ManhwatokError) as e:
        move_post("20260926-0002", "new", store.accounts, tools.posts)
    assert "stays on its account" in str(e.value)
