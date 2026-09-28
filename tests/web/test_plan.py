"""The Plan page: a week's calendar of every account's slots and posts, with filling an empty
slot, moving a post to another and taking one off its time."""

import json
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("fastapi")

from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.theme import Theme  # noqa: E402
from manhwatok.web.jobs import RENDER  # noqa: E402
from tests.tui.helpers import NOW, make_ctx  # noqa: E402
from tests.unit.fakes import FakeMetadata, manhwa, post  # noqa: E402
from tests.web.helpers import client_for, wait_job  # noqa: E402

PARIS, SEOUL = ZoneInfo("Europe/Paris"), ZoneInfo("Asia/Seoul")
# NOW is Wednesday 16 September 2026, 14:00 in Paris.
THU = datetime(2026, 9, 17, 19, 0, tzinfo=PARIS)  # reads' "thu 19:00", tomorrow
MON = datetime(2026, 9, 21, 19, 0, tzinfo=PARIS)  # its "mon 19:00", next Monday
SEOUL_THU = datetime(2026, 9, 17, 9, 0, tzinfo=SEOUL)  # seoul's free "thu 09:00"
SEOUL_MON = datetime(2026, 9, 21, 9, 0, tzinfo=SEOUL)  # seoul's taken "mon 09:00"
GONE = datetime(2026, 9, 16, 13, 0, tzinfo=PARIS)  # today, an hour before NOW
LONG_AGO = datetime(2026, 9, 15, 19, 0, tzinfo=PARIS)  # yesterday evening
READS, SEOUL_POST = "20260917-0001", "20260918-0002"
ISEKAI = Theme(name="isekai", tags=["Isekai"], title="Manhwa where the MC is *reborn*")
PICKS = [manhwa(anilist_id=i, title=f"Title {i}") for i in (1, 2, 3)]


def _ctx(tmp_path, posts=(), reads_slots=("thu 19:00", "mon 19:00", "wed 13:00")):
    """Two accounts in two time zones — reads, with a slot that has already gone, and seoul —
    both able to make a post, and whatever posts the test wants on them."""
    ctx = make_ctx(tmp_path, metadata=FakeMetadata(results=PICKS))
    ctx.store.themes.add(ISEKAI)
    ctx.store.accounts.add(
        Account(handle="reads", slots=list(reads_slots), rotation=["theme:isekai"],
                timezone="Europe/Paris")
    )
    ctx.store.accounts.add(
        Account(handle="seoul", slots=["mon 09:00", "thu 09:00"], rotation=["theme:isekai"],
                timezone="Asia/Seoul")
    )
    for each in posts:
        ctx.tools.posts.save(each)
    return ctx


def _taken_posts():
    """reads' tomorrow filled, seoul's next Monday filled: every other slot is free."""
    return [
        post(id=READS, account="reads", scheduled_at=THU),
        post(id=SEOUL_POST, account="seoul", scheduled_at=SEOUL_MON),
    ]


def _last_job(client):
    return wait_job(client, client.app.state.jobs.recent()[0].id)


def _notice(response) -> dict:
    return json.loads(response.headers["HX-Trigger"])["notice"]


def _schedules(ctx) -> dict:
    return {p.id: p.scheduled_at for p in ctx.tools.posts.list()}


# --- the calendar -----------------------------------------------------------------------------

def test_the_page_is_the_weeks_calendar_with_one_row_per_account(tmp_path):
    with client_for(_ctx(tmp_path, _taken_posts())) as client:
        html = client.get("/plan").text
    assert "<html" in html and 'id="plan-grid"' in html
    assert html.count('class="plan-account"') == 2  # reads, seoul
    for day in ("Wed 16 Sep", "Thu 17 Sep", "Mon 21 Sep", "Tue 22 Sep"):
        assert day in html
    assert READS in html and SEOUL_POST in html  # the filled slots show their posts
    assert f"/posts?post={READS}" in html  # a click opens it in Posts
    assert 'href="/plan?week=1' in html and 'href="/plan?week=-1' in html  # a week at a time


def test_the_grid_is_a_fragment_that_refreshes_itself(tmp_path):
    with client_for(_ctx(tmp_path, _taken_posts())) as client:
        page = client.get("/plan").text
        grid = client.get("/plan/grid").text
    assert "<html" not in grid and 'class="plan-cell"' in grid
    assert 'hx-trigger="changed-posts from:body, changed-store from:body"' in page


def test_stepping_a_week_shows_that_weeks_seven_days(tmp_path):
    with client_for(_ctx(tmp_path, _taken_posts())) as client:
        ahead = client.get("/plan", params={"week": 1}).text
        behind = client.get("/plan", params={"week": -1}).text
    assert "Wed 23 Sep" in ahead and "Thu 17 Sep" not in ahead
    assert "Tue 15 Sep" in behind and "Wed 16 Sep" not in behind
    assert "/plan/fill" not in behind  # nothing to fill in a week that has been and gone


def test_filtering_by_account_shows_only_its_row(tmp_path):
    with client_for(_ctx(tmp_path, _taken_posts())) as client:
        one = client.get("/plan", params={"account": "seoul"}).text
    assert one.count('class="plan-account"') == 1
    assert "@seoul</a>" in one and "@reads</a>" not in one  # the row, not the filter's options


def test_a_free_slot_offers_a_fill_but_one_whose_time_has_gone_does_not(tmp_path):
    with client_for(_ctx(tmp_path, _taken_posts())) as client:
        html = client.get("/plan").text
    assert 'hx-post="/plan/fill"' in html
    assert 'class="past">past<' in html  # reads' "wed 13:00" went by an hour ago


def test_a_taken_slot_shows_the_post_with_upload_move_and_unschedule(tmp_path):
    with client_for(_ctx(tmp_path, _taken_posts())) as client:
        html = client.get("/plan").text
    assert '<span class="dot" data-status="not rendered">' in html
    assert f'hx-get="/posts/{READS}/upload"' in html
    assert f'hx-post="/plan/{READS}/unschedule"' in html


def test_an_account_with_no_slots_is_told_how_to_set_them(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.store.accounts.add(Account(handle="reads", slots=[]))
    with client_for(ctx) as client:
        html = client.get("/plan").text
    assert "--slots" in html


# --- filling ----------------------------------------------------------------------------------

def test_filling_one_free_slot_makes_one_post_there(tmp_path):
    ctx = _ctx(tmp_path, _taken_posts())
    with client_for(ctx) as client:
        told = client.post("/plan/fill", data={"account": "reads", "when": MON.isoformat()})
        job = _last_job(client)
    made = job.outcome.split()[2]
    assert job.outcome.startswith("made post") and _schedules(ctx)[made] == MON
    assert _notice(told)["level"] == "info"


def test_filling_the_same_slot_again_makes_nothing_new(tmp_path):
    ctx = _ctx(tmp_path, _taken_posts())
    with client_for(ctx) as client:
        client.post("/plan/fill", data={"account": "@reads", "when": MON.isoformat()})
        _last_job(client)
        again = client.post("/plan/fill", data={"account": "reads", "when": MON.isoformat()})
        failed = _last_job(client)
    made = [p for p in ctx.tools.posts.list() if p.scheduled_at == MON]
    assert len(made) == 1
    assert failed.failed and "already has a post" in failed.outcome
    assert _notice(again)["level"] == "info"  # the page is never broken by it


def test_filling_a_time_that_has_passed_says_so(tmp_path):
    ctx = _ctx(tmp_path, _taken_posts())
    with client_for(ctx) as client:
        client.post("/plan/fill", data={"account": "reads", "when": GONE.isoformat()})
        job = _last_job(client)
    assert job.failed and "already passed" in job.outcome
    assert all(p.scheduled_at != GONE for p in ctx.tools.posts.list())


def test_fill_all_fills_every_account_that_has_slots(tmp_path):
    ctx = _ctx(tmp_path, _taken_posts())
    with client_for(ctx) as client:
        told = client.post("/plan/fill-all", data={"week": 0, "account": ""})
        job = _last_job(client)
    assert job.outcome == "made 2 posts"  # reads' Monday and seoul's Thursday
    assert _schedules(ctx)[READS] == THU  # untouched: that one was already filled
    assert {p.account for p in ctx.tools.posts.list() if p.scheduled_at in (MON, SEOUL_THU)} == {
        "reads",
        "seoul",
    }
    assert _notice(told)["text"].startswith("filling")


def test_fill_all_for_one_account_leaves_the_others_alone(tmp_path):
    ctx = _ctx(tmp_path, _taken_posts())
    with client_for(ctx) as client:
        client.post("/plan/fill-all", data={"week": 0, "account": "seoul"})
        job = _last_job(client)
    assert job.outcome == "made 1 post"  # seoul's free Thursday, and nothing of reads'
    assert all(p.scheduled_at != MON for p in ctx.tools.posts.list())


def test_a_fill_waits_for_the_render_lane(tmp_path):
    ctx = _ctx(tmp_path, _taken_posts())
    with client_for(ctx) as client:
        release = threading.Event()
        running = client.app.state.jobs.start(
            RENDER, "drawing", lambda io: (release.wait(5), "done")[1]
        )
        told = client.post("/plan/fill", data={"account": "reads", "when": MON.isoformat()})
        release.set()
        wait_job(client, running.id)
    assert _notice(told)["level"] == "warning"
    assert "try again when it's done" in _notice(told)["text"]


# --- moving and unscheduling ------------------------------------------------------------------

def test_the_move_menu_lists_only_that_accounts_free_slots(tmp_path):
    with client_for(_ctx(tmp_path, _taken_posts())) as client:
        reads = client.get(f"/plan/move/{READS}", params={"week": 0}).text
        seoul = client.get(f"/plan/move/{SEOUL_POST}", params={"week": 0}).text
    assert "<html" not in reads  # a fragment
    assert "to an empty slot of @reads" in reads and "@@" not in reads
    assert "Mon 21 Sep 19:00" in reads and "09:00" not in reads
    assert "Thu 17 Sep 09:00" in seoul and "19:00" not in seoul
    assert "Thu 17 Sep 19:00" not in reads  # its own slot, already taken
    assert "Wed 16 Sep" not in reads  # nothing behind us, and no past slot


def test_the_move_menu_refuses_a_sent_post_and_one_with_no_account(tmp_path):
    sent = post(id="20260919-0003", account="reads", scheduled_at=MON, sent_at=NOW)
    alone = post(id="20260920-0004", scheduled_at=THU)
    with client_for(_ctx(tmp_path, [sent, alone])) as client:
        first = client.get(f"/plan/move/{sent.id}").text
        second = client.get(f"/plan/move/{alone.id}").text
        gone = client.get("/plan/move/20260921-0005").text
    assert "already sent" in first and "Mon 21 Sep" not in first
    assert "no account" in second
    assert "20260921-0005" in gone and "<html" not in gone


def test_moving_a_post_puts_it_on_the_slot_chosen(tmp_path):
    ctx = _ctx(tmp_path, _taken_posts())
    with client_for(ctx) as client:
        moved = client.post(f"/plan/{READS}/schedule", data={"when": MON.isoformat()})
    assert _schedules(ctx)[READS] == MON
    assert moved.status_code == 200 and not moved.text  # the menu closes
    events = json.loads(moved.headers["HX-Trigger"])
    assert events["changed-posts"] is True and "moves to" in events["notice"]["text"]


def test_a_time_that_is_no_time_says_so_rather_than_breaking(tmp_path):
    ctx = _ctx(tmp_path, _taken_posts())
    with client_for(ctx) as client:
        told = client.post(f"/plan/{READS}/schedule", data={"when": "sometime soon"})
    assert told.status_code == 200 and _notice(told)["level"] == "error"
    assert _schedules(ctx)[READS] == THU  # left where it was


def test_unscheduling_clears_the_time_but_keeps_the_post(tmp_path):
    ctx = _ctx(tmp_path, _taken_posts())
    with client_for(ctx) as client:
        told = client.post(f"/plan/{READS}/unschedule")
    assert _schedules(ctx)[READS] is None
    assert ctx.tools.posts.get(READS) is not None
    assert json.loads(told.headers["HX-Trigger"])["changed-posts"] is True


# --- overdue and sent -------------------------------------------------------------------------

def test_posts_past_their_time_sit_on_top_in_red(tmp_path):
    late = post(id="20260915-0006", account="reads", scheduled_at=LONG_AGO)
    with client_for(_ctx(tmp_path, [*_taken_posts(), late])) as client:
        html = client.get("/plan").text
    assert 'class="plan-overdue"' in html and "20260915-0006" in html
    assert html.count('class="plan-day') == 7  # the calendar still shows its own seven days
    assert 'hx-post="/plan/20260915-0006/unschedule"' in html


def test_a_sent_post_is_greyed_and_keeps_its_slot(tmp_path):
    sent = post(id="20260919-0003", account="reads", scheduled_at=MON, sent_at=NOW)
    with client_for(_ctx(tmp_path, [sent], reads_slots=("mon 19:00",))) as client:
        html = client.get("/plan").text
    assert 'class="plan-post is-sent"' in html
    assert 'hx-post="/plan/20260919-0003/unschedule"' not in html
    assert 'class="plan-overdue"' not in html  # a sent post is never overdue
