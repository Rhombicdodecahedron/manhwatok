from manhwatok.adapters.fs_posts import FsPostRepository
from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.songs import set_post_song, song_for
from manhwatok.domain.account import Account
from tests.unit.fakes import post


def test_song_for_follows_the_account(tmp_path):
    with SqliteStore(tmp_path / "m.db") as store:
        store.accounts.add(Account(handle="reads", song="Acct"))
        assert song_for(post(account="reads"), store.accounts) == "Acct"
        assert song_for(post(account="reads", song="Own"), store.accounts) == "Own"
        assert song_for(post(), store.accounts) == ""


def test_song_for_a_removed_account_is_empty(tmp_path):
    with SqliteStore(tmp_path / "m.db") as store:
        assert song_for(post(account="gone"), store.accounts) == ""


def test_set_post_song_saves_trimmed_and_can_go_back_to_the_account(tmp_path):
    posts = FsPostRepository(tmp_path / "posts")
    posts.save(post())
    assert set_post_song("20260914-a3f9", "  Own  ", posts).song == "Own"
    assert posts.get("20260914-a3f9").song == "Own"
    set_post_song("20260914-a3f9", None, posts)
    assert posts.get("20260914-a3f9").song is None
