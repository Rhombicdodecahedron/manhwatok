import json

import pytest

pytest.importorskip("fastapi")

from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.theme import Theme  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import FakeMetadata, manhwa  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402


def _results():
    return [
        manhwa(anilist_id=1, title="Solo Leveling", chapters=200, genres=["Action"],
               description="A weak hunter becomes the strongest. More text."),
        manhwa(anilist_id=2, title='Evil <script>alert("x")</script>', chapters=80,
               description='He said "run". Then ran.'),
        manhwa(anilist_id=3, title="Omniscient Reader", chapters=150),
    ]


def _ctx(tmp_path, results=None):
    found = _results() if results is None else results
    ctx = make_ctx(tmp_path, metadata=FakeMetadata(results=found))
    ctx.store.accounts.add(Account(handle="reads"))
    ctx.store.themes.add(
        Theme(name="regression", tags=["Time Manipulation"], title="Regression *hits*")
    )
    return ctx


def _notice(response):
    return json.loads(response.headers["HX-Trigger"])["notice"]


def test_the_page_offers_accounts_and_themes(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        html = client.get("/new").text
    assert '<a href="/new" aria-current="page"' in html
    assert '<option value="reads">@reads</option>' in html
    assert 'value="regression"' in html and 'data-title="Regression *hits*"' in html
    assert 'hx-post="/new/search"' in html and 'id="results"' in html


def test_a_search_by_tags_shows_every_result_picked_with_its_hook(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        form = {"account": "reads", "tags": "Regression, Revenge", "limit": "12", "chapters": "on"}
        response = client.post("/new/search", data=form)
    html = response.text
    query = ctx.metadata.queries[0]
    assert (query.tags, query.limit, query.sort.value, query.min_tag_rank) == (
        ["Regression", "Revenge"], 12, "score", 60)
    assert html.count('class="candidate"') == 3
    assert html.count('aria-pressed="true"') == 3  # the TUI's prefill: every result, in order
    picks = html[html.index('id="picks"'):]  # the candidates' <template>s hold copies too
    assert picks[: picks.index("</ol>")].count('<li class="pick"') == 3
    assert 'name="hook-1" value="A weak hunter becomes the strongest."' in html
    draft = client.app.state.drafts.get(html.split('name="draft" value="')[1].split('"')[0])
    assert [m.anilist_id for m in draft.candidates] == [1, 2, 3] and draft.account == "reads"


def test_candidate_text_is_escaped(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        html = client.post("/new/search", data={"tags": "x"}).text
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert 'value="He said &#34;run&#34;."' in html


def test_a_theme_search_uses_the_theme(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        client.post("/new/search", data={"theme": "regression", "limit": "5"})
    query = ctx.metadata.queries[0]
    assert (query.tags, query.limit) == (["Time Manipulation"], 5)


@pytest.mark.parametrize(
    ("form", "message"),
    [
        ({}, "pick a theme or give at least one tag or genre"),
        ({"theme": "regression", "tags": "x"}, "use either a theme or tags/genres, not both"),
        ({"tags": "x", "limit": "99"}, "How many must be 1–50"),
        ({"tags": "x", "min_rank": "abc"}, "Min tag rank must be a number"),
    ],
)
def test_a_search_that_cannot_run_says_why(tmp_path, form, message):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post("/new/search", data=form)
    assert _notice(response) == {"text": message, "level": "error"}
    assert ctx.metadata.queries == []


def test_an_anilist_failure_is_a_notice(tmp_path):
    from manhwatok.domain.errors import MetadataError

    class Down(FakeMetadata):
        def search(self, query):
            raise MetadataError("AniList timed out")

    ctx = make_ctx(tmp_path, metadata=Down())
    with client_for(ctx) as client:
        response = client.post("/new/search", data={"tags": "x"})
    assert _notice(response) == {"text": "AniList timed out", "level": "error"}


def test_no_results_says_what_to_try(tmp_path):
    with client_for(_ctx(tmp_path, results=[])) as client:
        html = client.post("/new/search", data={"tags": "x"}).text
    assert "Nothing matched" in html


def test_drafts_keep_the_latest_searches_only():
    from manhwatok.domain.errors import ManhwatokError
    from manhwatok.web.drafts import Drafts

    drafts = Drafts(keep=2)
    first = drafts.add([manhwa()], None, None)
    drafts.add([manhwa()], None, None)
    drafts.add([manhwa()], None, None)
    with pytest.raises(ManhwatokError) as e:
        drafts.get(first.id)
    assert str(e.value) == "this search is gone — search again"
