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


from tests.web.helpers import wait_job  # noqa: E402


def _search(client, **form):
    html = client.post("/new/search", data={"account": "reads", "tags": "x", **form}).text
    return html.split('name="draft" value="')[1].split('"')[0]


def test_saving_keeps_the_posted_order_and_hooks_and_renders(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        draft = _search(client)
        response = client.post("/new/save", data={
            "draft": draft, "title": "Manhwa where the MC *wins*",
            "pick": ["3", "1"], "hook-3": "He read it all.", "hook-1": "Weakest to strongest.",
            "hook-2": "never picked", "hashtags": "", "accent": "", "emojis": "", "art": "",
            "cover": "hero",
        })
        post_id = response.headers["HX-Redirect"].split("post=")[1]
        job = wait_job(client, client.app.state.jobs.recent()[0].id)
    post = ctx.tools.posts.get(post_id)
    assert [(i.manhwa.anilist_id, i.hook) for i in post.items] == [
        (3, "He read it all."), (1, "Weakest to strongest.")]
    assert (post.title, post.account, post.cover.value) == (
        "Manhwa where the MC *wins*", "reads", "hero"
    )
    assert [m.anilist_id for m in post.candidates] == [1, 2, 3]
    assert _notice(response)["text"] == f"saved post {post_id} — rendering it…"
    assert job.outcome == f"rendered post {post_id}"
    assert (ctx.tools.posts.folder(post_id) / "01.png").is_file()


def test_a_theme_search_saves_the_theme_on_the_post(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        html = client.post("/new/search", data={"theme": "regression"}).text
        draft = html.split('name="draft" value="')[1].split('"')[0]
        response = client.post("/new/save", data={"draft": draft, "title": "T", "pick": ["1"]})
        wait_job(client, client.app.state.jobs.recent()[0].id)
    post_id = response.headers["HX-Redirect"].split("post=")[1]
    assert ctx.tools.posts.get(post_id).theme == "regression"


@pytest.mark.parametrize(
    ("form", "message"),
    [
        ({"title": "", "pick": ["1"]}, "title"),  # check_picks: a title is needed
        ({"title": "T"}, "pick"),  # no picks
        ({"title": "T", "pick": ["1", "1"]}, "twice"),
        ({"title": "T", "pick": ["99"]}, "not in this search"),
        ({"title": "T", "pick": ["1"], "accent": "blue"}, "accent"),
    ],
)
def test_a_save_that_cannot_go_through_says_why_and_saves_nothing(tmp_path, form, message):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        draft = _search(client)
        response = client.post("/new/save", data={"draft": draft, **form})
    notice = _notice(response)
    assert notice["level"] == "error" and message in notice["text"].lower()
    assert "HX-Redirect" not in response.headers
    assert ctx.tools.posts.list() == []


def test_a_search_that_is_gone_asks_to_search_again(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post("/new/save", data={"draft": "old", "title": "T", "pick": ["1"]})
    assert _notice(response) == {"text": "this search is gone — search again", "level": "error"}
    assert ctx.tools.posts.list() == []


def test_a_save_during_another_render_saves_and_says_to_render_later(tmp_path):
    import threading

    from manhwatok.web.jobs import RENDER

    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        draft = _search(client)
        release = threading.Event()
        job = client.app.state.jobs.start(
            RENDER, "render post a", lambda io: release.wait(5) and "ok"
        )
        response = client.post("/new/save", data={"draft": draft, "title": "T", "pick": ["1"]})
        release.set()
        wait_job(client, job.id)
    post_id = response.headers["HX-Redirect"].split("post=")[1]
    assert _notice(response) == {
        "text": f"saved post {post_id} — render it when render post a is done",
        "level": "warning",
    }
    assert ctx.tools.posts.get(post_id).items[0].manhwa.anilist_id == 1


def test_a_search_is_used_up_by_its_save_so_a_double_click_makes_one_post(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        draft = _search(client)
        form = {"draft": draft, "title": "T", "pick": ["1"]}
        first = client.post("/new/save", data=form)
        second = client.post("/new/save", data=form)
        wait_job(client, client.app.state.jobs.recent()[0].id)
    assert "HX-Redirect" in first.headers
    assert _notice(second) == {"text": "this search is gone — search again", "level": "error"}
    assert len(ctx.tools.posts.list()) == 1


def test_a_failed_save_keeps_the_search_for_another_try(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        draft = _search(client)
        client.post("/new/save", data={"draft": draft, "title": "", "pick": ["1"]})
        retry = client.post("/new/save", data={"draft": draft, "title": "T", "pick": ["1"]})
        wait_job(client, client.app.state.jobs.recent()[0].id)
    assert "HX-Redirect" in retry.headers


def test_every_candidate_comes_with_its_hook_and_the_page_knows_the_cap(tmp_path):
    many = [
        manhwa(anilist_id=n, title=f"T{n}", description=f"Hook {n}. More.") for n in range(1, 4)
    ]
    with client_for(_ctx(tmp_path, results=many)) as client:
        html = client.post("/new/search", data={"tags": "x"}).text
    templates = html.split("<template")[1:]
    assert len(templates) == 3
    for n, template in enumerate(templates, 1):
        assert f'name="hook-{n}" value="Hook {n}."' in template
    assert 'data-max="33"' in html


def test_a_failed_search_leaves_the_results_on_the_page(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        response = client.post("/new/search", data={})
    assert response.headers["HX-Reswap"] == "none"
