from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app import fill_plan
from manhwatok.app.fill_plan import PlanRow, fill, overdue_rows, plan_rows, schedule_post
from manhwatok.domain.account import Account
from manhwatok.domain.errors import AccountNotFound, ManhwatokError
from tests.unit.fakes import make_tools, post

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)  # Tuesday, 12:00 in Paris
THU = datetime(2026, 9, 24, 19, 0, tzinfo=PARIS)
MON = datetime(2026, 9, 28, 19, 0, tzinfo=PARIS)


def _utc(when: datetime) -> datetime:
    return when.astimezone(timezone.utc)


# --- plan_rows -------------------------------------------------------------------------------


def test_every_slot_is_a_row_empty_until_a_post_takes_it():
    reads = Account(handle="reads", slots=["mon 19:00", "thu 19:00"])
    taken = post(id="20260922-aaaa", account="reads", scheduled_at=THU)

    rows = plan_rows([reads], [taken], NOW, 7)

    assert rows == [PlanRow(THU, reads, taken, True), PlanRow(MON, reads, None, True)]
    assert all(row.at.tzinfo == PARIS for row in rows)


def test_rows_of_several_accounts_come_in_time_order_each_in_its_own_zone():
    paris = Account(handle="paris", slots=["thu 19:00"])
    seoul = Account(handle="seoul", slots=["thu 09:00"], timezone="Asia/Seoul")

    rows = plan_rows([paris, seoul], [], NOW, 3)

    assert [(r.account.handle, r.at.hour) for r in rows] == [("seoul", 9), ("paris", 19)]
    assert rows[0].at.tzinfo == ZoneInfo("Asia/Seoul")


def test_a_post_scheduled_off_the_slots_still_shows():
    reads = Account(handle="reads", slots=["thu 19:00"])
    at = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)
    off = post(id="20260922-bbbb", account="reads", scheduled_at=at)

    rows = plan_rows([reads], [off], NOW, 7)

    assert rows == [
        PlanRow(datetime(2026, 9, 23, 10, 0, tzinfo=PARIS), reads, off, False),
        PlanRow(THU, reads, None, True),
    ]
    assert rows[0].at.tzinfo == PARIS


def test_an_account_without_slots_shows_only_its_scheduled_posts():
    reads = Account(handle="reads")
    one = post(id="20260922-cccc", account="reads", scheduled_at=THU)
    assert plan_rows([reads], [one], NOW, 7) == [PlanRow(THU, reads, one, False)]


def test_two_posts_on_one_slot_are_two_rows():
    reads = Account(handle="reads", slots=["thu 19:00"])
    a = post(id="20260922-aaaa", account="reads", scheduled_at=THU)
    b = post(id="20260922-bbbb", account="reads", scheduled_at=_utc(THU))  # the same instant

    rows = plan_rows([reads], [b, a], NOW, 3)

    assert [(r.post.id, r.on_slot) for r in rows] == [
        ("20260922-aaaa", True),
        ("20260922-bbbb", True),
    ]


def test_other_accounts_unscheduled_and_out_of_range_posts_are_left_out():
    reads = Account(handle="reads")
    others = [
        post(id="20260922-aaaa", account="other", scheduled_at=THU),
        post(id="20260922-bbbb", account=None, scheduled_at=THU),
        post(id="20260922-cccc", account="reads"),
        post(id="20260922-dddd", account="reads", scheduled_at=MON),  # past the 3 days
        post(id="20260922-eeee", account="reads", scheduled_at=NOW),  # not after now
    ]
    assert plan_rows([reads], others, NOW, 3) == []


# --- overdue_rows ----------------------------------------------------------------------------

LAST_THU = datetime(2026, 9, 17, 19, 0, tzinfo=PARIS)


def test_overdue_rows_are_unsent_posts_whose_time_is_past_oldest_first():
    reads = Account(handle="reads", slots=["thu 19:00"])
    seoul = Account(handle="seoul", timezone="Asia/Seoul")
    late = post(id="20260917-aaaa", account="reads", scheduled_at=_utc(LAST_THU))
    noon = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    later = post(id="20260921-bbbb", account="seoul", scheduled_at=noon)
    left_out = [
        post(id="20260917-cccc", account="reads", scheduled_at=LAST_THU, sent_at=LAST_THU),
        post(id="20260922-dddd", account="reads", scheduled_at=THU),  # still ahead
        post(id="20260917-eeee", account="reads"),  # never scheduled
        post(id="20260917-ffff", account="other", scheduled_at=LAST_THU),  # not listed
        post(id="20260917-gggg", account=None, scheduled_at=LAST_THU),
    ]

    rows = overdue_rows([reads, seoul], [later, *left_out, late], NOW)

    assert rows == [
        PlanRow(LAST_THU, reads, late, True),
        PlanRow(noon.astimezone(ZoneInfo("Asia/Seoul")), seoul, later, False),
    ]
    assert rows[0].at.tzinfo == PARIS


def test_a_post_scheduled_right_now_is_overdue():
    reads = Account(handle="reads")
    due = post(account="reads", scheduled_at=NOW)
    assert [r.post for r in overdue_rows([reads], [due], NOW)] == [due]
    assert plan_rows([reads], [due], NOW, 7) == []  # so it shows in one of the two, once


# --- fill ------------------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    with SqliteStore(tmp_path / "manhwatok.db") as s:
        yield s


@pytest.fixture
def ctx(tmp_path, store):
    """Just what fill uses; make_next_post itself is faked below."""
    return SimpleNamespace(store=store, tools=make_tools(tmp_path))


@pytest.fixture
def made(monkeypatch):
    """Fakes make_next_post: each call saves a new post for the account. Set `fail_after` to
    make the call after that many raise."""
    calls = SimpleNamespace(handles=[], warns=[], fail_after=None)

    def fake(ctx, handle, now, warn):
        if calls.fail_after is not None and len(calls.handles) >= calls.fail_after:
            raise ManhwatokError("nothing left to post in @reads's rotation")
        calls.handles.append(handle)
        warn(f"warned {len(calls.handles)}")
        new = post(id=ctx.tools.posts.new_id(now.date()), account="reads", created_at=now)
        ctx.tools.posts.save(new)
        return new

    monkeypatch.setattr(fill_plan, "make_next_post", fake)
    return calls


def _reads(store, slots=("mon 19:00", "thu 19:00")) -> Account:
    account = Account(handle="reads", slots=list(slots), rotation=["theme:isekai"])
    store.accounts.add(account)
    return account


def test_fill_makes_a_post_for_each_empty_slot_and_stamps_its_time(ctx, store, made):
    _reads(store)
    seen = []

    posts = fill(ctx, "@reads", NOW, warn=made.warns.append, on_post=seen.append)

    assert [p.scheduled_at for p in posts] == [THU, MON]
    assert seen == posts
    assert [ctx.tools.posts.get(p.id) for p in posts] == posts
    assert made.warns == ["warned 1", "warned 2"]


def test_fill_twice_makes_nothing_new(ctx, store, made):
    _reads(store)
    fill(ctx, "reads", NOW)

    assert fill(ctx, "reads", NOW) == []
    assert len(made.handles) == 2
    assert len(ctx.tools.posts.list()) == 2


def test_a_sent_post_keeps_its_slot(ctx, store, made):
    _reads(store)
    sent = post(id="20260920-aaaa", account="reads", scheduled_at=_utc(THU), sent_at=NOW)
    ctx.tools.posts.save(sent)

    [new] = fill(ctx, "reads", NOW)

    assert new.scheduled_at == MON


def test_fill_looks_only_as_far_as_days(ctx, store, made):
    _reads(store)
    assert [p.scheduled_at for p in fill(ctx, "reads", NOW, days=3)] == [THU]


@pytest.mark.parametrize("days", [0, 11])
def test_fill_days_must_be_one_to_ten(ctx, store, made, days):
    _reads(store)
    with pytest.raises(ManhwatokError, match="1–10 days"):
        fill(ctx, "reads", NOW, days=days)
    assert made.handles == []


def test_fill_an_account_without_slots_says_how_to_set_them(ctx, store, made):
    _reads(store, slots=())
    with pytest.raises(ManhwatokError, match="--slots"):
        fill(ctx, "reads", NOW)


def test_fill_an_unknown_account_fails(ctx, made):
    with pytest.raises(AccountNotFound):
        fill(ctx, "nobody", NOW)


def test_fill_stops_at_the_first_failure_and_keeps_what_it_made(ctx, store, made):
    _reads(store)
    made.fail_after = 1
    seen = []

    with pytest.raises(ManhwatokError, match="nothing left"):
        fill(ctx, "reads", NOW, on_post=seen.append)

    [kept] = ctx.tools.posts.list()
    assert seen == [kept] and kept.scheduled_at == THU
    made.fail_after = None
    [then] = fill(ctx, "reads", NOW)  # the next fill takes the slot left over
    assert then.scheduled_at == MON


def test_fill_with_the_real_next_post_builds_rendered_posts(tmp_path, store):
    from tests.unit.test_next_post import ISEKAI, _ctx

    store.themes.add(ISEKAI)
    real = _ctx(tmp_path, store)
    _reads(store, slots=["thu 19:00"])

    [made] = fill(real, "reads", NOW)

    assert made.theme == "isekai" and made.scheduled_at == THU
    assert real.tools.posts.get(made.id) == made
    assert store.accounts.get("reads").rotation_cursor == 0  # one item, taken and wrapped


# --- schedule --------------------------------------------------------------------------------


def test_schedule_reads_the_time_in_the_posts_account_zone(tmp_path, store):
    posts = make_tools(tmp_path).posts
    store.accounts.add(Account(handle="seoul", timezone="Asia/Seoul"))
    posts.save(post(account="seoul"))

    done = schedule_post(posts, store.accounts, "20260914-a3f9", "2026-09-24 19:00", NOW)

    assert _utc(done.scheduled_at) == datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    assert posts.get(done.id) == done


@pytest.mark.parametrize("account", [None, "gone"])
def test_schedule_without_an_account_reads_paris_time(tmp_path, store, account):
    posts = make_tools(tmp_path).posts
    posts.save(post(account=account))

    done = schedule_post(posts, store.accounts, "20260914-a3f9", "thu 19:00", NOW)

    assert done.scheduled_at == THU


def test_schedule_none_clears_it(tmp_path, store):
    posts = make_tools(tmp_path).posts
    posts.save(post(scheduled_at=THU))

    done = schedule_post(posts, store.accounts, "20260914-a3f9", None, NOW)

    assert done.scheduled_at is None and posts.get(done.id).scheduled_at is None


def test_a_sent_post_cant_be_scheduled(tmp_path, store):
    posts = make_tools(tmp_path).posts
    posts.save(post(sent_at=NOW))
    with pytest.raises(ManhwatokError, match="already sent"):
        schedule_post(posts, store.accounts, "20260914-a3f9", "thu 19:00", NOW)
