import pytest

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.login_account import forget_login, login_account, saved_login
from manhwatok.domain.account import Account
from manhwatok.domain.errors import AccountNotFound, InvalidName, StorageError, UploadUnavailable
from tests.unit.fakes import FakeUploader


@pytest.fixture
def store(tmp_path):
    with SqliteStore(tmp_path / "m.db") as s:
        s.accounts.add(Account(handle="reads"))
        yield s


def test_login_tells_the_user_then_opens_the_accounts_browser(store):
    uploader = FakeUploader()
    messages = []
    account = login_account("@Reads", store.accounts, uploader, messages.append)
    assert account.handle == "reads"
    assert messages == ["Log in to @reads in the Chrome window, then quit that Chrome (⌘Q)."]
    assert uploader.logins == ["reads"]
    assert uploader.events == ["login", "close"]


def test_login_unknown_account_opens_nothing(store):
    uploader = FakeUploader()
    messages = []
    with pytest.raises(AccountNotFound, match="no account @ghost"):
        login_account("ghost", store.accounts, uploader, messages.append)
    with pytest.raises(InvalidName):
        login_account("no spaces", store.accounts, uploader, messages.append)
    assert (uploader.events, messages) == ([], [])


def test_login_closes_the_browser_when_it_fails(store):
    uploader = FakeUploader(error=UploadUnavailable("upload needs: …"))
    with pytest.raises(UploadUnavailable):
        login_account("reads", store.accounts, uploader, lambda _: None)
    assert uploader.events == ["login", "close"]


def test_saved_login_is_the_accounts_profile_folder(tmp_path):
    assert saved_login(tmp_path, "reads") is None
    (tmp_path / "reads").mkdir()
    assert saved_login(tmp_path, "@Reads") == tmp_path / "reads"


def test_forget_login_deletes_the_folder(tmp_path):
    browser_dir = tmp_path / "browsers"
    browser_dir.mkdir()
    folder = browser_dir / "reads"
    (folder / "Default").mkdir(parents=True)
    (folder / "Default" / "Cookies").write_bytes(b"x")
    forget_login(browser_dir, "reads")
    assert not folder.exists()


def test_a_linked_saved_login_is_never_followed(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "keep.txt").write_text("mine")
    browser_dir = tmp_path / "browsers"
    browser_dir.mkdir()
    (browser_dir / "reads").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    message = "the saved TikTok login for @reads is a link — delete it yourself: "
    for step in (saved_login, forget_login):
        with pytest.raises(StorageError) as e:
            step(browser_dir, "reads")
        assert str(e.value) == message + str(browser_dir / "reads")
    assert (tmp_path / "elsewhere" / "keep.txt").read_text() == "mine"


def test_forget_login_failure_is_a_storage_error(tmp_path, monkeypatch):
    browser_dir = tmp_path / "browsers"
    browser_dir.mkdir()
    (browser_dir / "reads").mkdir()

    def boom(path):
        raise OSError("busy")

    monkeypatch.setattr("manhwatok.app.login_account.shutil.rmtree", boom)
    with pytest.raises(StorageError, match="could not delete the saved login"):
        forget_login(browser_dir, "reads")


def test_saved_login_and_forget_reject_paths_outside_browser_dir(tmp_path, monkeypatch):
    # Create a sentinel file in the parent directory
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("data")
    browser_dir = tmp_path / "browsers"
    browser_dir.mkdir()

    # Monkeypatch normalize_handle to return ".." so the path would escape
    monkeypatch.setattr("manhwatok.app.login_account.normalize_handle", lambda h: "..")

    # saved_login should reject the path
    with pytest.raises(InvalidName):
        saved_login(browser_dir, "@anything")

    # forget_login should reject the path with new signature
    with pytest.raises(InvalidName):
        forget_login(browser_dir, "@anything")

    # Verify the sentinel and parent directory still exist
    assert sentinel.exists()
    assert tmp_path.exists()


def test_forget_login_cannot_delete_sibling_directories(tmp_path, monkeypatch):
    # Create a sibling directory to protect
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    (sibling / "data.txt").write_text("important")

    browser_dir = tmp_path / "browsers"
    browser_dir.mkdir()

    # Monkeypatch normalize_handle to return "../sibling" to try to escape
    monkeypatch.setattr("manhwatok.app.login_account.normalize_handle", lambda h: "../sibling")

    # forget_login should reject the path
    with pytest.raises(InvalidName):
        forget_login(browser_dir, "@attacker")

    # Verify sibling directory and its contents still exist
    assert sibling.exists()
    assert (sibling / "data.txt").read_text() == "important"
