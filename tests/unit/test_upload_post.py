from datetime import datetime, timezone

import pytest

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.render_post import render_post
from manhwatok.app.upload_post import upload_post
from manhwatok.domain.account import Account
from manhwatok.domain.errors import (
    AccountNotFound,
    DraftError,
    ManhwatokError,
    NotLoggedIn,
    NotRendered,
    PostNotFound,
)
from manhwatok.ports.uploader import UploadReport
from tests.unit.fakes import FakeUploader, make_tools, post

NOW = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)
POST_ID = "20260914-a3f9"


@pytest.fixture
def store(tmp_path):
    with SqliteStore(tmp_path / "m.db") as s:
        s.accounts.add(Account(handle="reads"))
        yield s


def _posts(tmp_path, render=True, **fields):
    tools = make_tools(tmp_path)
    tools.posts.save(post(**{"account": "reads", **fields}))
    if render:
        render_post(POST_ID, tools)
    return tools.posts


class Answer:
    """The terminal question: records what was asked (as an event too) and answers `yes`."""

    def __init__(self, uploader: FakeUploader, yes: bool):
        self.uploader, self.yes = uploader, yes
        self.questions: list[str] = []

    def __call__(self, question: str) -> bool:
        self.questions.append(question)
        self.uploader.events.append("confirm")
        return self.yes


def _upload(posts, store, uploader, yes=True, messages=None, debug=False, **sound):
    answer = Answer(uploader, yes)
    posted = upload_post(
        POST_ID,
        posts,
        store.accounts,
        store.history,
        uploader,
        answer,
        (messages if messages is not None else []).append,
        now=NOW,
        debug=debug,
        themes=store.themes,
        **sound,
    )
    return posted, answer


def test_yes_records_the_titles_and_marks_the_post_sent(tmp_path, store):
    posts = _posts(tmp_path)
    uploader = FakeUploader()
    messages = []
    posted, answer = _upload(posts, store, uploader, messages=messages)
    assert posted is True
    folder = posts.folder(POST_ID)
    [(handle, slides, title, description, sound, debug)] = uploader.uploads
    assert handle == "reads"
    assert slides == [folder / f"0{n}.png" for n in range(1, 6)]
    assert title == "Manhwa where the MC regresses"
    assert description == (
        "1. Title 1\n2. Title 2\n3. Title 3\n\n#manhwa #manhwarecommendation #webtoon "
        "#manhwatiktok"
    )
    assert (sound, debug) == (None, False)
    assert uploader.events == ["upload", "confirm", "close"]  # window open while asking
    assert answer.questions == ["Posted on @reads?"]
    assert store.history.recent("reads", NOW) == {1, 2, 3}
    assert posts.get(POST_ID).sent_at == NOW
    assert messages == [
        "attached 5 slides",
        "typed the title",
        "typed the description",
        f"slides and caption.txt: {folder}",
        "check the post in the browser and click Post yourself",
    ]


def test_no_records_nothing_and_still_closes_the_browser(tmp_path, store):
    posts = _posts(tmp_path)
    uploader = FakeUploader()
    posted, _ = _upload(posts, store, uploader, yes=False)
    assert posted is False
    assert uploader.events == ["upload", "confirm", "close"]
    assert store.history.recent("reads", NOW) == set()
    assert posts.get(POST_ID).sent_at is None


def test_problems_are_shown_and_the_question_is_still_asked(tmp_path, store):
    posts = _posts(tmp_path)
    report = UploadReport(
        attached=True,
        captioned=False,
        problems=["caption box not found — paste caption.txt yourself"],
        debug_dir=tmp_path / "debug" / "x",
    )
    uploader = FakeUploader(report)
    messages = []
    posted, answer = _upload(posts, store, uploader, messages=messages, debug=True)
    assert posted is True
    assert uploader.uploads[0][5] is True
    assert messages[:3] == [
        "attached 5 slides",
        "caption box not found — paste caption.txt yourself",
        f"debug files: {tmp_path / 'debug' / 'x'} (page.html can hold account details — "
        "check it before sharing)",
    ]
    assert answer.questions == ["Posted on @reads?"]


def _account_with_sounds(store, sounds=("solo leveling", "dark aria")):
    store.accounts.update(Account(handle="reads", sounds=list(sounds), emojis="🔥"))


def test_it_asks_which_of_the_accounts_sounds_to_use(tmp_path, store):
    _account_with_sounds(store)
    posts = _posts(tmp_path)
    uploader = FakeUploader(UploadReport(True, True, [], titled=True, sound="Dark Aria (01:00)"))
    offered = []
    messages = []

    def choose(sounds):
        offered.append(sounds)
        uploader.events.append("choose")
        return sounds[1]

    _upload(posts, store, uploader, messages=messages, choose_sound=choose)
    assert offered == [["solo leveling", "dark aria"]]
    assert uploader.events == ["choose", "upload", "confirm", "close"]  # asked before the window
    assert uploader.uploads[0][4] == "dark aria"
    assert "added the sound Dark Aria (01:00)" in messages


@pytest.mark.parametrize(
    ("sounds", "given", "chosen", "expected"),
    [
        (("solo leveling",), "  night drive ", "unused", "night drive"),  # --sound wins
        (("solo leveling",), "", "unused", None),  # --no-sound
        (("solo leveling",), None, None, None),  # "no sound" picked
        ((), None, "unused", None),  # nothing to pick from: not asked
    ],
)
def test_sound_choice(tmp_path, store, sounds, given, chosen, expected):
    _account_with_sounds(store, sounds)
    posts = _posts(tmp_path)
    uploader = FakeUploader()

    def choose(options):
        assert chosen != "unused", "should not ask"
        return chosen

    _upload(posts, store, uploader, sound=given, choose_sound=choose)
    assert uploader.uploads[0][4] == expected


def test_a_browser_failure_closes_it_and_asks_nothing(tmp_path, store):
    posts = _posts(tmp_path)
    uploader = FakeUploader(error=NotLoggedIn("@reads is not logged in"))
    with pytest.raises(NotLoggedIn):
        _upload(posts, store, uploader)
    assert uploader.events == ["upload", "close"]
    assert posts.get(POST_ID).sent_at is None


def test_uploading_a_sent_post_again_says_so(tmp_path, store):
    posts = _posts(tmp_path, sent_at=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc))
    messages = []
    _upload(posts, store, FakeUploader(), yes=False, messages=messages)
    assert messages[0] == f"post {POST_ID} was already marked sent on 2026-09-14 — uploading again"


def test_yes_on_an_old_post_counts_its_titles_as_posted_now(tmp_path, store):
    posts = _posts(tmp_path, sent_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    store.history.record("reads", POST_ID, [1, 2, 3], datetime(2026, 7, 1, tzinfo=timezone.utc))
    _upload(posts, store, FakeUploader())
    assert store.history.recent("reads", NOW) == {1, 2, 3}
    assert posts.get(POST_ID).sent_at == NOW


@pytest.mark.parametrize(
    ("fields", "render", "error", "match"),
    [
        ({"items": []}, False, DraftError, "has no items"),
        ({"account": None}, True, ManhwatokError, "has no account — build it with --account"),
        ({"account": "ghost"}, True, AccountNotFound, "no account @ghost"),
        ({}, False, NotRendered, f"run: manhwatok render {POST_ID}"),
    ],
)
def test_checks_before_opening_the_browser(tmp_path, store, fields, render, error, match):
    posts = _posts(tmp_path, render=render, **fields)
    uploader = FakeUploader()
    with pytest.raises(error, match=match):
        _upload(posts, store, uploader)
    assert uploader.events == []


def test_unknown_post(tmp_path, store):
    uploader = FakeUploader()
    with pytest.raises(PostNotFound):
        _upload(make_tools(tmp_path).posts, store, uploader)
    assert uploader.events == []


# --- sounds per theme ------------------------------------------------------------------------


def _themed(tmp_path, store, theme_sounds, account_sounds=("account song",), theme="murim"):
    from manhwatok.domain.theme import Theme

    store.accounts.update(Account(handle="reads", sounds=list(account_sounds)))
    if theme_sounds is not None:
        store.themes.add(Theme(name=theme, tags=["Martial Arts"], title="T", sounds=theme_sounds))
    return _posts(tmp_path, theme=theme)


def test_the_posts_theme_sounds_come_before_the_accounts(tmp_path, store):
    posts = _themed(tmp_path, store, ["phonk one", "phonk two"])
    offered = []
    _upload(posts, store, FakeUploader(), choose_sound=lambda s: (offered.append(s), s[0])[1])
    assert offered == [["phonk one", "phonk two", "account song"]]


def test_a_post_with_no_theme_is_offered_the_accounts_sounds(tmp_path, store):
    store.accounts.update(Account(handle="reads", sounds=["account song"]))
    posts = _posts(tmp_path)
    offered = []
    _upload(posts, store, FakeUploader(), choose_sound=lambda s: (offered.append(s), None)[1])
    assert offered == [["account song"]]


def test_a_theme_removed_since_the_post_was_built_is_not_an_error(tmp_path, store):
    posts = _themed(tmp_path, store, None, theme="gone")
    offered = []
    _upload(posts, store, FakeUploader(), choose_sound=lambda s: (offered.append(s), None)[1])
    assert offered == [["account song"]]


def test_a_sound_on_both_the_theme_and_the_account_is_offered_once(tmp_path, store):
    posts = _themed(tmp_path, store, ["shared song"], account_sounds=("shared song", "other"))
    offered = []
    _upload(posts, store, FakeUploader(), choose_sound=lambda s: (offered.append(s), None)[1])
    assert offered == [["shared song", "other"]]


def test_a_theme_with_sounds_and_an_account_without_still_offers_them(tmp_path, store):
    posts = _themed(tmp_path, store, ["phonk one"], account_sounds=())
    offered = []
    _upload(posts, store, FakeUploader(), choose_sound=lambda s: (offered.append(s), s[0])[1])
    assert offered == [["phonk one"]]


def _chapter_posts(tmp_path, store):
    """A rendered chapter post of @reads, its part recorded as built and not yet published."""
    from PIL import Image

    from manhwatok.domain.chapter import PartRecord
    from tests.unit.fakes import chapter_part, chapter_post

    tools = make_tools(tmp_path)
    folder = tools.posts.folder(POST_ID)
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for n in (1, 2):
        names.append(f"panel-{n:03d}.png")
        Image.new("RGB", (27, 48), (30 * n, 60, 90)).save(folder / names[-1])
    tools.posts.save(
        chapter_post(chapter=chapter_part(panels=names, to_panel=2), account="reads")
    )
    render_post(POST_ID, tools)
    store.chapters.record_part(
        PartRecord(
            anilist_id=1, number="12", language="en", part=1, parts=2, post_id=POST_ID,
            built_at=NOW,
        )
    )
    return tools.posts


def test_yes_marks_a_chapter_posts_part_published(tmp_path, store):
    posts = _chapter_posts(tmp_path, store)
    posted, _ = _upload(posts, store, FakeUploader(), chapters=store.chapters)
    assert posted is True
    assert store.chapters.parts(1)[0].published_at == NOW


def test_no_leaves_a_chapter_posts_part_unpublished(tmp_path, store):
    posts = _chapter_posts(tmp_path, store)
    _upload(posts, store, FakeUploader(), yes=False, chapters=store.chapters)
    assert store.chapters.parts(1)[0].published_at is None
