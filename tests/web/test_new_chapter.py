"""New post's Chapter tab: a title's next part, as `chapter next` and `chapter build`."""

import json

import pytest

pytest.importorskip("fastapi")

from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.chapter import ChapterRecord  # noqa: E402
from manhwatok.domain.models import ChapterSourceName  # noqa: E402
from manhwatok.ports.chapters import ChapterInfo  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import FakeChapterPages, FakeMetadata, manhwa  # noqa: E402
from tests.web.helpers import client_for, wait_job  # noqa: E402

BOXER = manhwa(anilist_id=119174, title="The Boxer")
CH12 = ChapterInfo("ch-12", "12", "Talent", "en", 36)
CH13 = ChapterInfo("ch-13", "13", "", "en", 37)


def _ctx(tmp_path):
    pages = FakeChapterPages(chapters=[CH12, CH13])
    ctx = make_ctx(tmp_path, metadata=FakeMetadata([BOXER]), chapter_pages=pages)
    ctx.store.accounts.add(Account(handle="reads", hashtags="#reads", emojis="📚"))
    return ctx


def _track(ctx):
    ctx.store.chapters.record_chapters(
        [
            ChapterRecord(
                source=ChapterSourceName.MANGADEX,
                anilist_id=BOXER.anilist_id,
                manhwa_title=BOXER.title,
                number=info.number,
                chapter_id=info.chapter_id,
                language=info.language,
                chapter_title=info.title,
                pages=info.pages,
            )
            for info in (CH12, CH13)
        ]
    )
    ctx.store.cache.put(f"manhwa:{BOXER.anilist_id}", BOXER.model_dump_json())


def _notice(response):
    return json.loads(response.headers["HX-Trigger"])["notice"]


def test_the_page_offers_both_kinds_of_post(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        listing = client.get("/new").text
        chapter = client.get("/new?type=chapter").text
    assert 'href="/new?type=chapter"' in listing and 'hx-post="/new/search"' in listing
    assert 'hx-post="/new/search"' not in chapter
    assert 'hx-post="/new/chapter/check"' in chapter and 'hx-post="/new/chapter/build"' in chapter
    assert '<option value="reads">@reads</option>' in chapter
    assert 'name="language" value="en"' in chapter
    for source in ChapterSourceName:
        assert f'<option value="{source.value}">' in chapter


def test_the_chapter_tab_lists_tracked_titles(tmp_path):
    ctx = _ctx(tmp_path)
    _track(ctx)
    with client_for(ctx) as client:
        html = client.get("/new?type=chapter").text
    assert f'<option value="{BOXER.anilist_id}">The Boxer</option>' in html


def test_check_says_which_part_comes_next(tmp_path):
    ctx = _ctx(tmp_path)
    _track(ctx)
    with client_for(ctx) as client:
        response = client.post(
            "/new/chapter/check", data={"tracked": str(BOXER.anilist_id), "language": "en"}
        )
    assert response.status_code == 200
    assert "The Boxer · mangadex — next: chapter 12, part 1" in response.text


def test_check_by_name_lists_a_new_title_from_its_source(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post("/new/chapter/check", data={"text": "The Boxer", "language": "en"})
    assert "next: chapter 12, part 1" in response.text
    assert ctx.store.chapters.titles()  # now tracked


@pytest.mark.parametrize(
    "form, message",
    [
        ({"language": "en"}, "name a title, or its AniList id"),
        ({"text": "The Boxer", "language": ""}, "give a chapter language, e.g. en"),
        ({"text": "The Boxer", "language": "en", "part": "0"}, "part must be a whole number"),
        ({"text": "The Boxer", "language": "en", "accent": "nope"}, "accent"),
    ],
)
def test_a_chapter_form_that_cannot_run_says_why(tmp_path, form, message):
    with client_for(_ctx(tmp_path)) as client:
        for url in ("/new/chapter/check", "/new/chapter/build"):
            response = client.post(url, data=form)
            notice = _notice(response)
            assert notice["level"] == "error" and message in notice["text"]
            assert response.headers["HX-Reswap"] == "none"
    assert not client.app.state.jobs.recent()


def test_build_makes_the_next_part_in_the_render_lane(tmp_path):
    ctx = _ctx(tmp_path)
    _track(ctx)
    with client_for(ctx) as client:
        response = client.post(
            "/new/chapter/build",
            data={
                "tracked": str(BOXER.anilist_id),
                "language": "en",
                "account": "reads",
                "title": "Boxer *hits*",
            },
        )
        job_id = response.headers["HX-Redirect"].removeprefix("/jobs/")
        job = wait_job(client, job_id)
    assert not job.failed, job.outcome
    posts = ctx.tools.posts.list()
    assert len(posts) == 1
    post = posts[0]
    assert (post.chapter.number, post.chapter.part, post.account) == ("12", 1, "reads")
    assert post.title == "Boxer *hits*" and post.hashtags == "#reads"
    assert job.outcome.startswith(f"post {post.id} · chapter 12 part 1/")


def test_build_when_everything_is_built_fails_the_job(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.chapter_tools.pages.listed = []
    with client_for(ctx) as client:
        response = client.post("/new/chapter/build", data={"text": "The Boxer", "language": "en"})
        job = wait_job(client, response.headers["HX-Redirect"].removeprefix("/jobs/"))
    assert job.failed and "nothing" in job.outcome.lower()
    assert not ctx.tools.posts.list()
