from manhwatok.adapters.anilist import AniListSource
from manhwatok.adapters.cached_chapters import CachedChapterSource
from manhwatok.app.container import build_chapter_source, build_metadata
from manhwatok.config import Settings


def test_build_chapter_source_returns_cached_chapter_source_and_creates_db(tmp_path):
    source = build_chapter_source(Settings(data_dir=tmp_path))
    assert isinstance(source, CachedChapterSource)
    assert (tmp_path / "manhwatok.db").exists()


def test_build_metadata_returns_anilist_source(tmp_path):
    assert isinstance(build_metadata(Settings(data_dir=tmp_path)), AniListSource)
