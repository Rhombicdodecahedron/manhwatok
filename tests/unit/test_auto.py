from datetime import datetime, timedelta, timezone

import pytest

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.auto import LATE, MAX_TRIES, tick
from manhwatok.app.context import AppContext
from manhwatok.app.render_post import render_post
from manhwatok.config import Settings
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import ArtSourceName
from manhwatok.domain.theme import Theme
from manhwatok.ports.uploader import UploadReport
from tests.unit.fakes import (
    FakeArtSource,
    FakeChapters,
    FakeMetadata,
    FakeUploader,
    make_chapter_tools,
    make_tools,
    manhwa,
    post,
)

NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)  # Tuesday, 12:00 in Paris
PICKS = [manhwa(anilist_id=i, title=f"Title {i}", description=f"Hook {i}.") for i in (1, 2, 3)]
ISEKAI = Theme(name="isekai", tags=["Isekai"], title="Manhwa where the MC is *reborn*")


class Catalogue(FakeMetadata):
    def search(self, query):
        self.queries.append(query)
        return list(PICKS)


@pytest.fixture
def ctx(tmp_path):
    with SqliteStore(tmp_path / "manhwatok.db") as store:
        store.themes.add(ISEKAI)
        yield AppContext(
            settings=Settings(data_dir=tmp_path),
            store=store,
            metadata=Catalogue(PICKS),
            chapters=FakeChapters(),
            tools=make_tools(tmp_path),
            art_sources={name: FakeArtSource() for name in ArtSourceName},
            chapter_tools=make_chapter_tools(tmp_path),
            uploader_factory=lambda: None,
        )


def _account(ctx, handle="reads", rotation=("theme:isekai",), slots=("thu 19:00",), **fields):
    account = Account(handle=handle, rotation=list(rotation), slots=list(slots), **fields)
    ctx.store.accounts.add(account)
    return account


def _due(ctx, post_id, ago=timedelta(minutes=10), account="reads", **fields):
    """A rendered post of `account` whose time came `ago`."""
    saved = post(id=post_id, account=account, scheduled_at=NOW - ago, **fields)
    ctx.tools.posts.save(saved)
    render_post(post_id, ctx.tools)
    return saved


def _posting(posted=True, error=None):
    """A phone that taps Post itself (or doesn't manage to), and the accounts it was built for."""
    report = UploadReport(attached=True, captioned=True, problems=[], titled=True, posted=posted)
    phone = FakeUploader(report, error)
    asked = []

    def uploader(account):
        asked.append(account.handle)
        return phone

    return phone, uploader, asked


# --- filling ---------------------------------------------------------------------------------


def test_a_tick_fills_the_empty_slots_of_every_account_that_has_a_plan(ctx):
    _account(ctx, "reads")
    _account(ctx, "more", slots=["fri 08:00", "sat 08:00"])
    _account(ctx, "idle", slots=[])
    _account(ctx, "aimless", rotation=[])

    report = tick(ctx, NOW, days=7)

    assert sorted((p.account, p.scheduled_at.strftime("%a")) for p in report.made) == [
        ("more", "Fri"), ("more", "Sat"), ("reads", "Thu"),
    ]
    assert {p.id for p in ctx.tools.posts.list()} == {p.id for p in report.made}


def test_a_second_tick_makes_nothing_new(ctx):
    _account(ctx)
    tick(ctx, NOW, days=7)
    assert tick(ctx, NOW, days=7).made == []


def test_an_account_that_fails_is_reported_and_the_others_are_still_filled(ctx):
    log = []
    _account(ctx, "broken", rotation=["theme:nope"])
    _account(ctx, "reads")

    report = tick(ctx, NOW, days=7, log=log.append)

    assert [p.account for p in report.made] == ["reads"]
    assert any("@broken" in line and "nope" in line for line in log)


def test_each_new_post_is_logged_with_its_slot(ctx):
    log = []
    _account(ctx)
    [made] = tick(ctx, NOW, days=7, log=log.append).made
    assert any(made.id in line and "@reads" in line and "Thu 24 Sep 19:00" in line for line in log)


# --- uploading -------------------------------------------------------------------------------


def test_a_due_post_of_an_account_that_opted_in_goes_out_through_its_phone(ctx):
    _account(ctx, auto_upload=True, phone="SERIAL1")
    _due(ctx, "20260922-aaaa")
    phone, uploader, asked = _posting()

    report = tick(ctx, NOW, uploader=uploader)

    assert report.sent == ["20260922-aaaa"] and asked == ["reads"]
    assert [u[0] for u in phone.uploads] == ["reads"]
    assert phone.uploads[0][6] is None  # posted now: its time has come, nothing to schedule
    assert ctx.tools.posts.get("20260922-aaaa").sent_at == NOW
    assert phone.events[-1] == "close"


def test_an_account_that_did_not_opt_in_is_only_filled(ctx):
    _account(ctx)
    _due(ctx, "20260922-aaaa")
    phone, uploader, _ = _posting()

    report = tick(ctx, NOW, uploader=uploader)

    assert report.sent == [] and phone.uploads == []
    assert ctx.tools.posts.get("20260922-aaaa").sent_at is None


def test_without_an_uploader_nothing_goes_out(ctx):
    _account(ctx, auto_upload=True)
    _due(ctx, "20260922-aaaa")
    assert tick(ctx, NOW).sent == []
    assert ctx.tools.posts.get("20260922-aaaa").sent_at is None


def test_a_post_the_phone_did_not_post_itself_is_never_recorded_as_sent(ctx):
    log = []
    _account(ctx, auto_upload=True)
    _due(ctx, "20260922-aaaa")
    phone, uploader, _ = _posting(posted=False)

    report = tick(ctx, NOW, uploader=uploader, log=log.append)

    kept = ctx.tools.posts.get("20260922-aaaa")
    assert report.sent == [] and report.failed == ["20260922-aaaa"]
    assert kept.sent_at is None and kept.auto_tries == 1
    assert ctx.store.history.recent("reads", NOW - timedelta(days=1)) == set()
    assert any("20260922-aaaa" in line and "did not go out" in line for line in log)


def test_a_post_that_keeps_failing_is_left_for_the_queue_after_two_tries(ctx):
    log = []
    _account(ctx, auto_upload=True)
    _due(ctx, "20260922-aaaa")
    phone, uploader, _ = _posting(posted=False)

    for _ in range(MAX_TRIES + 2):
        tick(ctx, NOW, uploader=uploader, log=log.append)

    assert len(phone.uploads) == MAX_TRIES
    assert ctx.tools.posts.get("20260922-aaaa").auto_tries == MAX_TRIES
    assert sum("Queue" in line for line in log) == 1  # said once, when it gives up


def test_an_upload_that_fails_outright_counts_as_a_try(ctx):
    log = []
    _account(ctx, auto_upload=True)
    _due(ctx, "20260922-aaaa")
    phone, uploader, _ = _posting(error=ManhwatokError("no phone is plugged in"))

    report = tick(ctx, NOW, uploader=uploader, log=log.append)

    assert report.failed == ["20260922-aaaa"]
    assert ctx.tools.posts.get("20260922-aaaa").auto_tries == 1
    assert any("no phone is plugged in" in line for line in log)


def test_a_phone_that_cannot_even_be_reached_counts_as_a_try(ctx):
    _account(ctx, auto_upload=True)
    _due(ctx, "20260922-aaaa")

    def uploader(account):
        raise ManhwatokError("the phone extra isn't installed")

    assert tick(ctx, NOW, uploader=uploader).failed == ["20260922-aaaa"]
    assert ctx.tools.posts.get("20260922-aaaa").auto_tries == 1


def test_one_post_goes_out_per_tick_oldest_first(ctx):
    _account(ctx, auto_upload=True)
    _due(ctx, "20260922-bbbb", ago=timedelta(minutes=5))
    _due(ctx, "20260922-aaaa", ago=timedelta(hours=2))
    phone, uploader, _ = _posting()

    assert tick(ctx, NOW, uploader=uploader).sent == ["20260922-aaaa"]
    assert tick(ctx, NOW, uploader=uploader).sent == ["20260922-bbbb"]
    assert tick(ctx, NOW, uploader=uploader).sent == []


def test_a_post_too_long_overdue_is_left_alone(ctx):
    _account(ctx, auto_upload=True)
    _due(ctx, "20260922-aaaa", ago=LATE + timedelta(minutes=1))
    phone, uploader, _ = _posting()

    assert tick(ctx, NOW, uploader=uploader).sent == []
    assert phone.uploads == []


def test_a_post_whose_time_has_not_come_waits(ctx):
    _account(ctx, auto_upload=True)
    _due(ctx, "20260922-aaaa", ago=timedelta(minutes=-30))
    phone, uploader, _ = _posting()
    assert tick(ctx, NOW, uploader=uploader).sent == [] and phone.uploads == []


def test_a_post_already_sent_is_not_sent_again(ctx):
    _account(ctx, auto_upload=True)
    _due(ctx, "20260922-aaaa", sent_at=NOW - timedelta(minutes=5))
    phone, uploader, _ = _posting()
    assert tick(ctx, NOW, uploader=uploader).sent == [] and phone.uploads == []


def test_an_account_with_no_sound_to_use_unasked_posts_without_one_and_says_so(ctx):
    log = []
    _account(ctx, auto_upload=True, sounds=["one", "two"])
    _due(ctx, "20260922-aaaa")
    phone, uploader, _ = _posting()

    tick(ctx, NOW, uploader=uploader, log=log.append)

    assert phone.uploads[0][4] is None
    assert any("without a sound" in line for line in log)


def test_an_accounts_default_sound_is_used(ctx):
    _account(ctx, auto_upload=True, sounds=["one", "two"], default_sound="two")
    _due(ctx, "20260922-aaaa")
    phone, uploader, _ = _posting()
    tick(ctx, NOW, uploader=uploader)
    assert phone.uploads[0][4] == "two"
