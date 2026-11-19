import pytest

# Settings read these at creation; a developer's own shell (e.g. MANHWATOK_UPLOADER=phone)
# must not change what the tests build.
UPLOAD_ENV = (
    "MANHWATOK_UPLOADER", "MANHWATOK_APPIUM_URL", "MANHWATOK_PHONE", "MANHWATOK_TIKTOK_APP",
    "MANHWATOK_AUTO_POST", "MANHWATOK_OLLAMA_URL",
)


@pytest.fixture(autouse=True)
def _no_upload_env(monkeypatch):
    for name in UPLOAD_ENV:
        monkeypatch.delenv(name, raising=False)
    # Ollama is on unless told otherwise, and a test must never reach a real one.
    monkeypatch.setenv("MANHWATOK_OLLAMA_MODEL", "off")
