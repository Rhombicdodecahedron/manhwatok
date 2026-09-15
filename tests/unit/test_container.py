from manhwatok.adapters.anilist import AniListSource
from manhwatok.adapters.cached_chapters import CachedChapterSource
from manhwatok.adapters.fs_posts import FsPostRepository
from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.container import build_chapter_source, build_metadata, build_posts, build_store
from manhwatok.config import Settings


def test_build_store_opens_the_database_in_the_data_dir(tmp_path):
    with build_store(Settings(data_dir=tmp_path)) as store:
        assert isinstance(store, SqliteStore)
    assert (tmp_path / "manhwatok.db").exists()


def test_build_chapter_source_caches_in_the_given_cache(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with build_store(settings) as store:
        assert isinstance(build_chapter_source(settings, store.cache), CachedChapterSource)


def test_build_posts_is_the_post_folder_repository(tmp_path):
    posts = build_posts(Settings(data_dir=tmp_path))
    assert isinstance(posts, FsPostRepository)
    assert posts.folder("20260914-a3f9") == tmp_path / "posts" / "20260914-a3f9"


def test_build_metadata_returns_anilist_source(tmp_path):
    assert isinstance(build_metadata(Settings(data_dir=tmp_path)), AniListSource)


def test_build_post_tools_wires_real_adapters(tmp_path):
    from manhwatok.adapters.cover_cache import CoverCache
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
