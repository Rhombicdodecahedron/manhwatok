from pathlib import Path

from manhwatok.config import Settings


def test_data_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path / "d"))
    assert Settings().data_dir == tmp_path / "d"


def test_data_dir_defaults_to_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("MANHWATOK_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert Settings().data_dir == tmp_path / "manhwatok"


def test_db_path_lives_in_data_dir():
    assert Settings(data_dir=Path("/x")).db_path == Path("/x/manhwatok.db")


def test_posts_and_covers_live_in_data_dir():
    s = Settings(data_dir=Path("/x"))
    assert s.posts_dir == Path("/x/posts")
    assert s.covers_dir == Path("/x/covers")


def test_browser_profiles_and_debug_files_live_in_data_dir():
    s = Settings(data_dir=Path("/x"))
    assert s.browser_dir == Path("/x/browser")
    assert s.debug_dir == Path("/x/debug")


def test_export_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MANHWATOK_EXPORT_DIR", str(tmp_path / "e"))
    assert Settings().export_dir == tmp_path / "e"


def test_export_dir_defaults_to_downloads(monkeypatch, tmp_path):
    monkeypatch.delenv("MANHWATOK_EXPORT_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Downloads").mkdir()
    assert Settings().export_dir == tmp_path / "Downloads" / "manhwatok"


def test_export_dir_falls_back_to_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("MANHWATOK_EXPORT_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert Settings().export_dir == tmp_path / "manhwatok"


def test_reddit_credentials_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("MANHWATOK_REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("MANHWATOK_REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("MANHWATOK_REDDIT_USER", "someone")
    s = Settings()
    assert (s.reddit_client_id, s.reddit_client_secret, s.reddit_user) == ("id", "secret", "someone")


def test_reddit_credentials_default_to_none_set(monkeypatch):
    for var in ("MANHWATOK_REDDIT_CLIENT_ID", "MANHWATOK_REDDIT_CLIENT_SECRET",
                "MANHWATOK_REDDIT_USER"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert (s.reddit_client_id, s.reddit_client_secret, s.reddit_user) == ("", "", "")


def test_pages_dir_sits_under_the_data_dir(tmp_path):
    from manhwatok.config import Settings

    assert Settings(data_dir=tmp_path).pages_dir == tmp_path / "pages"
