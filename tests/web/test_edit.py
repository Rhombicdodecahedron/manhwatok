import json
import threading

import pytest

pytest.importorskip("fastapi")

from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.web.jobs import RENDER  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import chapter_post, post  # noqa: E402
from tests.web.helpers import client_for, wait_job  # noqa: E402

PID, CHAPTER = "20260914-0002", "20260915-0003"


def _ctx(tmp_path, **kwargs):
    ctx = make_ctx(tmp_path, **kwargs)
    ctx.tools.posts.save(post(id=PID))
    render_post(PID, ctx.tools)
    ctx.tools.posts.save(chapter_post(id=CHAPTER))
    return ctx


def _notice(response):
    return json.loads(response.headers["HX-Trigger"])["notice"]


def _last_job(client):
    return wait_job(client, client.app.state.jobs.recent()[0].id)


def test_the_detail_links_to_the_edit_page(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        assert f'href="/posts/{PID}/edit"' in client.get(f"/posts/{PID}").text


def test_the_edit_page_shows_the_posts_texts_and_look(tmp_path):
    ctx = _ctx(tmp_path)
    p = ctx.tools.posts.get(PID)
    with client_for(ctx) as client:
        html = client.get(f"/posts/{PID}/edit").text
    assert 'id="texts"' in html and 'id="picks-section"' in html and 'id="art-section"' in html
    assert f'name="title" value="{p.title}"' in html
    assert f'name="hashtags" value="{p.hashtags}"' in html
    assert f'name="accent" value="{p.accent}"' in html
    assert '<option value="background"' in html and '<option value="hero"' in html


def test_a_chapter_post_edits_its_texts_only(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        html = client.get(f"/posts/{CHAPTER}/edit").text
    assert 'id="texts"' in html
    assert 'id="art-section"' not in html and 'id="picks-section"' not in html
    assert "draws its own panels" in html


def test_an_unknown_post_says_it_is_gone(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        response = client.get("/posts/20260101-0000/edit")
    assert response.status_code == 200 and "is gone" in response.text


def test_saving_texts_and_look_saves_then_renders(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/settings", data={
            "title": "Fresh *title*", "hashtags": "#x", "emojis": "🔥", "byline": "",
            "cta_title": "Which one?", "cta_follow": "Follow", "accent": "#ff5588",
            "art": "background", "cover": "hero",
        })
        job = _last_job(client)
    saved = ctx.tools.posts.get(PID)
    assert (saved.title, saved.accent, saved.art.value, saved.cover.value) == (
        "Fresh *title*", "#ff5588", "background", "hero")
    assert _notice(response) == {"text": f"saving post {PID}…", "level": "info"}
    assert job.outcome == f"saved texts and look — rendered post {PID}" and not job.failed


def test_bad_texts_are_refused_before_anything_changes(tmp_path):
    ctx = _ctx(tmp_path)
    before = ctx.tools.posts.get(PID)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/settings", data={"title": "T", "accent": "blue"})
    assert _notice(response)["level"] == "error" and "accent" in _notice(response)["text"]
    assert ctx.tools.posts.get(PID) == before
    assert client.app.state.jobs.recent() == []


def test_a_chapter_posts_art_style_is_refused(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{CHAPTER}/settings", data={"title": "T", "art": "quad"})
    assert "draws its own panels" in _notice(response)["text"]


def test_changes_wait_for_a_running_render(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        release = threading.Event()
        job = client.app.state.jobs.start(
            RENDER, "render post a", lambda io: release.wait(5) and "ok"
        )
        response = client.post(f"/posts/{PID}/settings", data={"title": "Changed"})
        release.set()
        wait_job(client, job.id)
    assert _notice(response)["level"] == "warning"
    assert ctx.tools.posts.get(PID).title != "Changed"


from tests.unit.fakes import manhwa  # noqa: E402


def _picky(tmp_path):
    """PID with three candidates: 1 and 2 picked (1 with its own picture), 3 not."""
    from manhwatok.domain.post import PostItem

    ctx = _ctx(tmp_path)
    cands = [
        manhwa(anilist_id=n, title=f"Title {n}", description=f"Hook {n}. More.") for n in (1, 2, 3)
    ]
    items = [PostItem(manhwa=cands[0], hook="one", custom_art="art-1.jpg"),
             PostItem(manhwa=cands[1], hook="two")]
    fresh = ctx.tools.posts.get(PID).model_copy(update={"candidates": cands, "items": items})
    ctx.tools.posts.save(fresh)
    (ctx.tools.posts.folder(PID) / "art-1.jpg").write_bytes(b"jpg")
    return ctx


def test_the_picks_editor_shows_the_posts_picks_and_its_other_candidates(tmp_path):
    with client_for(_picky(tmp_path)) as client:
        html = client.get(f"/posts/{PID}/picks").text
    assert f'hx-post="/posts/{PID}/picks"' in html and 'id="picks-form"' in html
    assert html.count('aria-pressed="true"') == 2 and html.count('aria-pressed="false"') == 1
    assert 'name="hook-1" value="one"' in html
    assert 'name="hook-3" value="Hook 3."' in html  # ready in its template


def test_editing_picks_keeps_each_kept_titles_picture(tmp_path):
    ctx = _picky(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/picks", data={
            "title": "T", "pick": ["3", "1"], "hook-3": "three", "hook-1": "first now",
        })
        job = _last_job(client)
    items = ctx.tools.posts.get(PID).items
    assert [(i.manhwa.anilist_id, i.hook, i.custom_art) for i in items] == [
        (3, "three", ""), (1, "first now", "art-1.jpg")]
    assert _notice(response)["text"] == f"saving post {PID}…"
    assert job.outcome == f"saved the picks — rendered post {PID}"


def test_a_pick_that_is_not_a_candidate_is_refused(tmp_path):
    ctx = _picky(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/picks", data={"title": "T", "pick": ["99"]})
    assert _notice(response)["level"] == "error"
    assert [i.manhwa.anilist_id for i in ctx.tools.posts.get(PID).items] == [1, 2]


from manhwatok.ports.art import ArtOption  # noqa: E402
from tests.unit.fakes import FakeArtSource  # noqa: E402

OPTIONS = [
    ArtOption("small", "https://pins.test/a.jpg", 400, 600, likes=5),
    ArtOption("big", "https://pins.test/b.jpg", 1200, 1800, likes=50),
]


def _arty(tmp_path, pins=None):
    ctx = _ctx(tmp_path, pins=pins or FakeArtSource(options={1: OPTIONS}))
    first = ctx.tools.posts.get(PID).items[0].manhwa.anilist_id
    return ctx, first


def test_each_pick_shows_its_picture_and_a_way_to_change_it(tmp_path):
    ctx, first = _arty(tmp_path)
    with client_for(ctx) as client:
        html = client.get(f"/posts/{PID}/art").text
    assert html.count('class="art-title"') == len(ctx.tools.posts.get(PID).items)
    assert f'hx-get="/posts/{PID}/art/{first}"' in html


def test_a_source_lists_its_pictures_in_the_order_asked(tmp_path):
    ctx, first = _arty(tmp_path)
    with client_for(ctx) as client:
        query = {"source": "pins", "order": "popular"}
        html = client.get(f"/posts/{PID}/art/{first}", params=query).text
    assert html.index("https://pins.test/b.jpg") < html.index("https://pins.test/a.jpg")
    assert html.count('class="art-option"') == 2
    assert "1200×1800" in html and "50 likes" in html


def test_a_failing_source_says_why_in_the_picker(tmp_path):
    from manhwatok.domain.errors import ManhwatokError

    why = "pinterest art needs gallery-dl: uv sync --extra pinterest"
    broken = FakeArtSource(error=ManhwatokError(why))
    ctx, first = _arty(tmp_path, pins=broken)
    with client_for(ctx) as client:
        response = client.get(f"/posts/{PID}/art/{first}", params={"source": "pins"})
    assert response.status_code == 200
    assert 'class="art-error"' in response.text and "gallery-dl" in response.text


def test_a_tag_with_covers_is_refused(tmp_path):
    ctx, first = _arty(tmp_path)
    with client_for(ctx) as client:
        html = client.get(f"/posts/{PID}/art/{first}", params={"source": "covers", "tag": "x"}).text
    assert "covers has no such vocabulary" in html


def test_using_a_picture_downloads_it_as_the_titles_art_and_renders(tmp_path):
    ctx, first = _arty(tmp_path)
    from manhwatok.domain.models import ArtSourceName

    pins = ctx.art_sources[ArtSourceName.PINS]
    with client_for(ctx) as client:
        html = client.get(f"/posts/{PID}/art/{first}", params={"source": "pins"}).text
        list_id = html.split('"list": "')[1].split('"')[0]
        chosen = {"list": list_id, "index": "1"}
        response = client.post(f"/posts/{PID}/art/{first}/use", data=chosen)
        job = _last_job(client)
    item = next(i for i in ctx.tools.posts.get(PID).items if i.manhwa.anilist_id == first)
    assert item.custom_art.startswith(f"art-{first}")
    assert pins.fetched == ["https://pins.test/b.jpg"]
    assert _notice(response)["text"] == f"changing post {PID}…"
    assert job.outcome == f"changed the picture of {item.manhwa.title} — rendered post {PID}"


def test_a_list_that_is_gone_asks_to_find_again(tmp_path):
    ctx, first = _arty(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/art/{first}/use", data={"list": "old", "index": "0"})
    assert _notice(response) == {
        "text": "this list is gone — find pictures again", "level": "error"
    }
