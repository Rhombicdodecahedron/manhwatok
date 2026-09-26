import pytest

from tests.tui.helpers import OPEN_CONTEXTS


@pytest.fixture(autouse=True)
def _never_the_real_data_dir(tmp_path, monkeypatch):
    """Anything that builds Settings() by itself lands in a temporary folder."""
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path / "default-data"))
    monkeypatch.setenv("MANHWATOK_EXPORT_DIR", str(tmp_path / "default-exports"))


@pytest.fixture(autouse=True)
def _close_contexts():
    yield
    while OPEN_CONTEXTS:
        OPEN_CONTEXTS.pop().close()
