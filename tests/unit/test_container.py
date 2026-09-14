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


def test_build_post_tools_wires_real_adapters(tmp_path):
    from manhwatok.adapters.cover_cache import CoverCache
    from manhwatok.adapters.fs_posts import FsPostRepository
    from manhwatok.adapters.pillow_renderer import PillowRenderer
    from manhwatok.app.container import build_post_tools

    def editor(text):
        return None

    tools = build_post_tools(Settings(data_dir=tmp_path), editor, print)
    assert isinstance(tools.posts, FsPostRepository)
    assert isinstance(tools.covers, CoverCache)
    assert isinstance(tools.renderer, PillowRenderer)
    assert tools.editor is editor
    assert tools.posts.folder("20260914-a3f9") == tmp_path / "posts" / "20260914-a3f9"
