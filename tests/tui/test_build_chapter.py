"""The Build tab's Chapter mode: a title's next part, as `chapter next` and `chapter build`."""

import threading

import pytest

pytest.importorskip("textual")

from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.chapter import ChapterRecord, PartRecord  # noqa: E402
from manhwatok.domain.models import ChapterSourceName  # noqa: E402
from manhwatok.ports.chapters import ChapterInfo  # noqa: E402
from manhwatok.tui.screens.build import BuildPane  # noqa: E402
from manhwatok.tui.screens.posts import PostsPane  # noqa: E402
from tests.tui.helpers import NOW, make_ctx, notes, run_app, wait_for  # noqa: E402
from tests.unit.fakes import FakeChapterPages, FakeMetadata, manhwa  # noqa: E402

BOXER = manhwa(anilist_id=119174, title="The Boxer")
KUBERA = manhwa(anilist_id=22, title="Kubera")
CH12 = ChapterInfo("ch-12", "12", "Talent", "en", 36)
CH13 = ChapterInfo("ch-13", "13", "", "en", 37)
FR1 = ChapterInfo("fr-1", "1", "", "fr", 20)


def _ctx(tmp_path, chapters=(CH12, CH13), **fields):
    pages = FakeChapterPages(chapters=list(chapters))
    ctx = make_ctx(
        tmp_path, metadata=FakeMetadata([BOXER, KUBERA]), chapter_pages=pages, **fields
    )
    ctx.store.accounts.add(Account(handle="reads", hashtags="#reads", emojis="📚"))
    return ctx, pages


def _track(ctx, title=BOXER, source=ChapterSourceName.MANGADEX, cached=True):
    """`title` as `chapter list` leaves it: its chapters on record (and itself in the cache)."""
    ctx.store.chapters.record_chapters(
        [
            ChapterRecord(
                source=source,
                anilist_id=title.anilist_id,
                manhwa_title=title.title,
                number=info.number,
                chapter_id=info.chapter_id,
                language=info.language,
                chapter_title=info.title,
                pages=info.pages,
            )
            for info in (CH12, CH13)
        ]
    )
    if cached:
        ctx.store.cache.put(f"manhwa:{title.anilist_id}", title.model_dump_json())


def _built(ctx, number, part, parts, title=BOXER):
    ctx.store.chapters.record_part(
        PartRecord(
            anilist_id=title.anilist_id,
            number=number,
            language="en",
            part=part,
            parts=parts,
            post_id=f"old-{number}-{part}",
            built_at=NOW,
        )
    )


async def _chapter_mode(app, pilot):
    await pilot.press("2")
    await pilot.pause()
    pane = app.query_one(BuildPane)
    pane.query_one("#mode-chapter").value = True
    await pilot.pause()
    return pane


async def _set(pilot, pane, **values):
    for name, value in values.items():
        pane.query_one(f"#{name.replace('_', '-')}").value = value
    await pilot.pause()


def _next_text(pane) -> str:
    return str(pane.query_one("#chapter-next").render())


def _shown(pane, widget_id) -> bool:
    """Whether the widget and every container up to the pane are displayed."""
    node = pane.query_one(f"#{widget_id}")
    while node is not pane:
        if not node.display:
            return False
        node = node.parent
    return True


# --- the mode switch ---------------------------------------------------------------------------


def test_list_mode_is_the_default_and_chapter_mode_swaps_the_form(tmp_path):
    ctx, _ = _ctx(tmp_path)

    async def scenario(app, pilot):
        await pilot.press("2")
        await pilot.pause()
        pane = app.query_one(BuildPane)
        assert pane.query_one("#mode-list").value is True
        for shown in ("theme", "tags", "search", "tag-search", "art", "account", "hashtags"):
            assert _shown(pane, shown), shown
        for hidden in ("chapter-title", "chapter-new-title", "chapter-build", "chapter-check"):
            assert not _shown(pane, hidden), hidden

        pane.query_one("#mode-chapter").value = True
        await pilot.pause()
        for shown in (
            "account",
            "chapter-title",
            "chapter-new-title",
            "chapter-source",
            "chapter-language",
            "chapter-post-title",
            "hashtags",
            "accent",
            "emojis",
            "chapter-check",
            "chapter-build",
        ):
            assert _shown(pane, shown), shown
        for hidden in ("theme", "tags", "search", "tag-search", "art", "title"):
            assert not _shown(pane, hidden), hidden
        assert pane.query_one("#chapter-language").value == "en"

        pane.query_one("#mode-list").value = True
        await pilot.pause()
        assert _shown(pane, "search") and not _shown(pane, "chapter-build")

    run_app(ctx, scenario)


def test_the_title_choices_are_the_tracked_titles(tmp_path):
    ctx, _ = _ctx(tmp_path)
    _track(ctx, BOXER)
    _track(ctx, KUBERA, source=ChapterSourceName.ASURA)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        select = pane.query_one("#chapter-title")
        assert [str(label) for label, _ in select._options[1:]] == ["Kubera", "The Boxer"]
        source = pane.query_one("#chapter-source")
        assert [value for _, value in source._options[1:]] == list(ChapterSourceName)

    run_app(ctx, scenario)


# --- check ---------------------------------------------------------------------------------------


def test_check_lists_a_new_title_and_shows_its_next_part(tmp_path):
    ctx, pages = _ctx(tmp_path)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_new_title="The Boxer")
        await pilot.click("#chapter-check")
        await wait_for(pilot, lambda: "next:" in _next_text(pane))
        assert _next_text(pane) == "The Boxer · mangadex — next: chapter 12, part 1"
        # now tracked: offered in the title choices
        await wait_for(pilot, lambda: len(pane.query_one("#chapter-title")._options) == 2)

    run_app(ctx, scenario)
    assert set(pages.listings) == {BOXER.anilist_id}
    assert pages.downloads == []  # checking builds nothing
    assert ctx.tools.posts.list() == []


def test_check_says_which_part_of_a_started_chapter_comes_next(tmp_path):
    ctx, pages = _ctx(tmp_path)
    _track(ctx)
    _built(ctx, "12", 1, 3)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_title=BOXER.anilist_id)
        pane.check_chapter()
        await wait_for(pilot, lambda: "next:" in _next_text(pane))
        assert _next_text(pane).endswith("next: chapter 12, part 2 of 3")

    run_app(ctx, scenario)
    assert pages.listings == []  # on record already: nothing asked of the source
    assert ctx.metadata.searches == []  # the tracked title came from the cache


def test_check_asks_the_source_again_when_everything_listed_is_built(tmp_path):
    ctx, pages = _ctx(tmp_path, chapters=(CH12, CH13))
    _track(ctx)
    _built(ctx, "12", 1, 1)
    _built(ctx, "13", 1, 1)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_title=BOXER.anilist_id)
        pane.check_chapter()
        await wait_for(pilot, lambda: "built" in _next_text(pane))
        assert _next_text(pane) == "The Boxer · mangadex — every listed chapter is built"

    run_app(ctx, scenario)
    assert pages.listings == [BOXER.anilist_id]


def test_check_finds_a_tracked_title_by_name_when_it_is_not_cached(tmp_path):
    ctx, _ = _ctx(tmp_path)
    _track(ctx, cached=False)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_title=BOXER.anilist_id)
        pane.check_chapter()
        await wait_for(pilot, lambda: "next:" in _next_text(pane))

    run_app(ctx, scenario)
    assert ctx.metadata.searches == ["The Boxer"]


def test_check_in_another_language(tmp_path):
    ctx, pages = _ctx(tmp_path, chapters=(CH12, FR1))

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_new_title="Boxer", chapter_language=" fr ")
        pane.check_chapter()
        await wait_for(pilot, lambda: "next:" in _next_text(pane))
        assert _next_text(pane).endswith("next: chapter 1, part 1")

    run_app(ctx, scenario)
    assert [c.number for c in ctx.store.chapters.chapters(BOXER.anilist_id, "fr")] == ["1"]


def test_the_typed_title_wins_over_the_chosen_one(tmp_path):
    ctx, pages = _ctx(tmp_path)
    _track(ctx, KUBERA)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_title=KUBERA.anilist_id, chapter_new_title="The Boxer")
        pane.check_chapter()
        await wait_for(pilot, lambda: "next:" in _next_text(pane))
        assert _next_text(pane).startswith("The Boxer")

    run_app(ctx, scenario)


def test_check_uses_the_source_asked_for(tmp_path):
    asura = FakeChapterPages(chapters=[CH13])
    ctx, mangadex = _ctx(tmp_path, chapter_sources={ChapterSourceName.ASURA: asura})

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_new_title="The Boxer", chapter_source=ChapterSourceName.ASURA)
        pane.check_chapter()
        await wait_for(pilot, lambda: "next:" in _next_text(pane))
        assert _next_text(pane) == "The Boxer · asura — next: chapter 13, part 1"

    run_app(ctx, scenario)
    assert (mangadex.listings, asura.listings) == ([], [BOXER.anilist_id])


@pytest.mark.parametrize(
    "values, message",
    [
        ({}, "name a title, or its AniList id"),
        ({"chapter_new_title": "Nothing like it"}, "AniList has nothing called 'Nothing like it'"),
        ({"chapter_new_title": "The Boxer", "chapter_language": " "}, "give a chapter language"),
    ],
)
def test_check_errors_show_as_notifications(tmp_path, values, message):
    ctx, pages = _ctx(tmp_path)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, **values)
        pane.check_chapter()
        await wait_for(pilot, lambda: any(n.startswith(message) for n in notes(app)))
        assert _next_text(pane) == ""

    run_app(ctx, scenario)
    assert pages.downloads == []


def test_check_shows_the_sources_error(tmp_path):
    ctx, _ = _ctx(tmp_path, chapters=())

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_new_title="The Boxer")
        pane.check_chapter()
        await wait_for(
            pilot, lambda: any("no English chapters to publish" in n for n in notes(app))
        )

    run_app(ctx, scenario)


# --- build ---------------------------------------------------------------------------------------


def test_build_makes_the_next_part_renders_it_and_shows_it_in_posts(tmp_path):
    ctx, pages = _ctx(tmp_path)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, account="reads", chapter_new_title="The Boxer")
        await pilot.click("#chapter-build")
        await wait_for(pilot, lambda: app.query_one("#tabs").active == "posts")
        [saved] = ctx.tools.posts.list()
        posts = app.query_one(PostsPane)
        assert posts.current_id == saved.id
        assert any(n.startswith(f"post {saved.id} · chapter 12 part 1/1 · ") for n in notes(app))
        assert "The Boxer: 2 chapters listed" in notes(app)  # progress, as renders report it
        assert "chapter 12: 3 pages" in notes(app)

    run_app(ctx, scenario)
    [saved] = ctx.tools.posts.list()
    assert (saved.chapter.number, saved.chapter.part) == ("12", 1)
    assert (saved.account, saved.hashtags, saved.emojis) == ("reads", "#reads", "📚")
    assert saved.title == "The Boxer *Chapter 12*"
    assert saved.created_at == NOW
    assert pages.downloads == ["ch-12"]
    assert len(ctx.tools.renderer.calls) == 1
    [part] = ctx.store.chapters.parts(BOXER.anilist_id)
    assert part.post_id == saved.id


def test_build_takes_the_style_overrides(tmp_path):
    ctx, _ = _ctx(tmp_path)
    _track(ctx)
    _built(ctx, "12", 1, 1)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(
            pilot,
            pane,
            account="reads",
            chapter_title=BOXER.anilist_id,
            chapter_post_title="Round *two*",
            hashtags="#boxing",
            accent="#ABCDEF",
            emojis=" 🥊 ",
        )
        pane.build_chapter()
        await wait_for(pilot, lambda: app.query_one("#tabs").active == "posts")

    run_app(ctx, scenario)
    [saved] = ctx.tools.posts.list()
    assert saved.chapter.number == "13"
    assert (saved.title, saved.hashtags, saved.accent, saved.emojis) == (
        "Round *two*",
        "#boxing",
        "#abcdef",
        "🥊",
    )


def test_build_lists_new_chapters_when_everything_on_record_is_built(tmp_path):
    ctx, pages = _ctx(tmp_path, chapters=(CH12, CH13))
    ctx.store.chapters.record_chapters(
        [
            ChapterRecord(
                source=ChapterSourceName.MANGADEX,
                anilist_id=BOXER.anilist_id,
                manhwa_title=BOXER.title,
                number="12",
                chapter_id="ch-12",
                language="en",
                pages=36,
            )
        ]
    )
    ctx.store.cache.put(f"manhwa:{BOXER.anilist_id}", BOXER.model_dump_json())
    _built(ctx, "12", 1, 1)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_title=BOXER.anilist_id)
        pane.build_chapter()
        await wait_for(pilot, lambda: ctx.tools.posts.list() != [])

    run_app(ctx, scenario)
    [saved] = ctx.tools.posts.list()
    assert saved.chapter.number == "13"


@pytest.mark.parametrize(
    "values, message",
    [
        ({}, "name a title, or its AniList id"),
        ({"chapter_new_title": "The Boxer", "accent": "cyan"}, "accent must look like #43c9e4"),
        ({"chapter_new_title": "Nothing like it"}, "AniList has nothing called"),
    ],
)
def test_build_errors_show_as_notifications_and_save_nothing(tmp_path, values, message):
    ctx, pages = _ctx(tmp_path)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, **values)
        pane.build_chapter()
        await wait_for(pilot, lambda: any(n.startswith(message) for n in notes(app)))
        await pilot.pause()
        assert app.query_one("#tabs").active == "build"

    run_app(ctx, scenario)
    assert ctx.tools.posts.list() == []
    assert pages.downloads == []


def test_build_waits_for_a_running_render(tmp_path):
    ctx, _ = _ctx(tmp_path)
    release = threading.Event()

    async def scenario(app, pilot):
        try:
            pane = await _chapter_mode(app, pilot)
            await _set(pilot, pane, chapter_new_title="The Boxer")
            app.start_render(lambda tools: release.wait(5), lambda _: None)
            pane.build_chapter()
            await pilot.pause()
            assert "still rendering — try again when it's done" in notes(app)
        finally:
            release.set()

    run_app(ctx, scenario)
    assert ctx.tools.posts.list() == []


def test_page_counts_show_in_the_form_not_as_notifications(tmp_path):
    from manhwatok.ports.chapters import PageCount

    class CountingPages(FakeChapterPages):
        def pages(self, chapter, progress=None):
            for n in (1, 2, 3):
                progress(PageCount(f"chapter {chapter.number}", "page", n, 3))
            return super().pages(chapter)

    pages = CountingPages(chapters=[CH12])
    ctx = make_ctx(tmp_path, metadata=FakeMetadata([BOXER]), chapter_pages=pages)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_new_title="The Boxer")
        pane.build_chapter()
        await wait_for(pilot, lambda: ctx.tools.posts.list() != [])
        await wait_for(pilot, lambda: _next_text(pane).startswith("post "))
        assert not any("page 1 of 3" in n for n in notes(app))

    run_app(ctx, scenario)


# --- a chosen chapter and part -----------------------------------------------------------------


def test_check_reports_the_chapter_and_part_asked_for(tmp_path):
    ctx, pages = _ctx(tmp_path)
    _track(ctx)
    _built(ctx, "12", 1, 3)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_title=BOXER.anilist_id, chapter_number="13")
        pane.check_chapter()
        await wait_for(pilot, lambda: "chapter 13" in _next_text(pane))
        assert _next_text(pane).endswith("asked for: chapter 13, part 1")

    run_app(ctx, scenario)


def test_check_reports_a_part_already_built_as_a_rebuild(tmp_path):
    ctx, _ = _ctx(tmp_path)
    _track(ctx)
    _built(ctx, "12", 1, 3)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_title=BOXER.anilist_id, chapter_number="12", chapter_part="1")
        pane.check_chapter()
        await wait_for(pilot, lambda: "chapter 12" in _next_text(pane))
        assert _next_text(pane).endswith("asked for: chapter 12, part 1 of 3 — built already")

    run_app(ctx, scenario)


def test_a_chosen_chapter_is_built_even_when_every_chapter_is_done(tmp_path):
    ctx, pages = _ctx(tmp_path)
    _track(ctx)
    _built(ctx, "12", 1, 1)
    _built(ctx, "13", 1, 1)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_title=BOXER.anilist_id, chapter_number="12", chapter_part="1")
        pane.build_chapter()
        await wait_for(pilot, lambda: "post " in _next_text(pane))
        assert "chapter 12 part 1" in _next_text(pane)

    run_app(ctx, scenario)
    assert pages.listings == []  # the record had it: no need to ask the source for more


def test_a_part_that_is_not_a_whole_number_is_refused(tmp_path):
    ctx, _ = _ctx(tmp_path)
    _track(ctx)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_title=BOXER.anilist_id, chapter_part="second")
        pane.check_chapter()
        await pilot.pause()
        assert any("part must be a whole number" in n for n in notes(app))

    run_app(ctx, scenario)


def test_an_unlisted_chapter_says_what_is_listed(tmp_path):
    ctx, _ = _ctx(tmp_path)
    _track(ctx)

    async def scenario(app, pilot):
        pane = await _chapter_mode(app, pilot)
        await _set(pilot, pane, chapter_title=BOXER.anilist_id, chapter_number="99")
        pane.check_chapter()
        await wait_for(pilot, lambda: bool(notes(app)))
        assert any("has no chapter 99" in n for n in notes(app))

    run_app(ctx, scenario)
