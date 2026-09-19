from manhwatok.app.art_options import fill_art, list_art
from manhwatok.app.title_extras import refresh_titles
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.post import PostItem
from manhwatok.ports.art import ArtOption
from tests.unit.fakes import FakeArtSource, FakeMetadata, make_tools, manhwa, post

PID = "20260914-a3f9"


def _tools(tmp_path, meta, messages=None):
    tools = make_tools(tmp_path, messages=messages)
    tools.metadata = meta
    old = PostItem(manhwa=manhwa(anilist_id=1, title="Log-in Murim", character_url="c1"), hook="h")
    new = PostItem(manhwa=manhwa(anilist_id=2, synonyms=["Known"]), hook="h")
    tools.posts.save(post(items=[old, new]))
    return tools


def test_older_titles_get_their_alternative_titles_and_characters(tmp_path):
    meta = FakeMetadata()
    meta.synonyms = {1: ["Murim Login"]}
    meta.character_urls = {1: ["c1", "c2"]}
    tools = _tools(tmp_path, meta)
    refreshed = refresh_titles(PID, tools)
    assert meta.extra_lookups == [[1]]
    m = tools.posts.get(PID).items[0].manhwa
    assert (m.synonyms, m.character_urls) == (["Murim Login"], ["c1", "c2"])
    assert refreshed.items[0].manhwa == m
    refresh_titles(PID, tools)
    assert meta.extra_lookups == [[1]]  # once


def test_a_title_with_no_alternatives_is_not_asked_about_again(tmp_path):
    meta = FakeMetadata()
    tools = _tools(tmp_path, meta)
    refresh_titles(PID, tools)
    refresh_titles(PID, tools)
    assert meta.extra_lookups == [[1]]
    assert tools.posts.get(PID).items[0].manhwa.synonyms == []


def test_an_outage_leaves_the_post_as_it_was(tmp_path):
    messages = []
    meta = FakeMetadata()
    meta.extra_error = MetadataError("AniList unreachable: boom")
    tools = _tools(tmp_path, meta, messages)
    assert refresh_titles(PID, tools).items[0].manhwa.synonyms is None
    assert any("AniList unreachable" in m for m in messages)


def test_art_searches_see_the_alternative_titles(tmp_path):
    meta = FakeMetadata()
    meta.synonyms = {1: ["Murim Login"]}
    tools = _tools(tmp_path, meta)
    seen = []

    class Source(FakeArtSource):
        def options(self, m, tag=None):
            seen.append(m.synonyms)
            return [ArtOption("a", f"https://x.test/{m.anilist_id}.jpg")]

    list_art(PID, 1, tools, Source())
    fill_art(PID, tools, Source())
    assert seen[0] == ["Murim Login"] and seen[1] == ["Murim Login"]
