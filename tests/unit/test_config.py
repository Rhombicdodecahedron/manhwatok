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
