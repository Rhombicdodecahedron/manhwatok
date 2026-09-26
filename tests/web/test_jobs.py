import threading
import time

import pytest

pytest.importorskip("fastapi")

from manhwatok.domain.errors import ManhwatokError  # noqa: E402
from manhwatok.web.jobs import BROWSER, RENDER, Busy, EventBus, JobRunner  # noqa: E402


def _events(q) -> list[tuple[str, dict]]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _pending(runner, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not runner.pending():
        assert time.monotonic() < deadline, "no question came"
        time.sleep(0.01)
    return runner.pending()[0]


def test_a_job_runs_reports_and_ends():
    bus = EventBus()
    q = bus.subscribe()
    runner = JobRunner(bus)

    def work(io):
        io.progress("one")
        io.progress("two")
        return "done"

    job = runner.wait(runner.start(RENDER, "render post x", work).id, 5)
    assert (job.log, job.outcome, job.failed, job.running) == (["one", "two"], "done", False, False)
    kinds = [(kind, data.get("state") or data.get("line")) for kind, data in _events(q)]
    assert kinds == [("job", "started"), ("log", "one"), ("log", "two"), ("job", "finished")]


def test_one_job_per_lane_the_other_lane_is_free():
    runner = JobRunner(EventBus())
    release = threading.Event()
    first = runner.start(RENDER, "render post a", lambda io: release.wait(5) and "ok")
    with pytest.raises(Busy) as e:
        runner.start(RENDER, "render post b", lambda io: "never")
    assert str(e.value) == "render post a is still going — try again when it's done"
    other = runner.start(BROWSER, "upload post c", lambda io: "ok")
    assert runner.wait(other.id, 5).outcome == "ok"
    assert runner.busy(RENDER) is first
    release.set()
    runner.wait(first.id, 5)
    assert runner.busy(RENDER) is None


def test_errors_end_the_job_not_the_lane():
    runner = JobRunner(EventBus())

    def expected(io):
        raise ManhwatokError("post x has no items")

    def bug(io):
        raise RuntimeError("oops")

    assert runner.wait(runner.start(RENDER, "a", expected).id, 5).outcome == (
        "error: post x has no items"
    )
    job = runner.wait(runner.start(RENDER, "b", bug).id, 5)
    assert (job.outcome, job.failed) == ("error: RuntimeError: oops", True)
    assert runner.wait(runner.start(RENDER, "c", lambda io: "fine").id, 5).outcome == "fine"


def test_a_question_waits_for_an_answer_and_the_first_answer_wins():
    bus = EventBus()
    q = bus.subscribe()
    runner = JobRunner(bus)
    choices = [("A", "a"), ("none", "")]
    job = runner.start(BROWSER, "upload", lambda io: f"chose {io.choose('Sound?', choices)}")
    question = _pending(runner)
    assert (question.text, question.choices, question.job_id) == ("Sound?", choices, job.id)
    assert job.question is question
    assert runner.answer(question.id, "a") is True
    assert runner.answer(question.id, "") is False  # a second tab, too late
    assert runner.wait(job.id, 5).outcome == "chose a"
    assert runner.pending() == [] and job.question is None
    kinds = [kind for kind, _ in _events(q)]
    assert kinds == ["job", "question", "answered", "job"]


def test_an_answer_must_be_one_of_the_choices():
    runner = JobRunner(EventBus())
    job = runner.start(BROWSER, "upload", lambda io: str(io.confirm("Posted?")))
    question = _pending(runner)
    assert runner.answer(question.id, "maybe") is False
    assert runner.answer("q999", "yes") is False
    assert runner.answer(question.id, "no") is True
    assert runner.wait(job.id, 5).outcome == "False"


def test_stopping_answers_no_and_refuses_new_jobs():
    runner = JobRunner(EventBus())
    job = runner.start(BROWSER, "upload", lambda io: f"posted={io.confirm('Posted?')}")
    _pending(runner)
    runner.stop()
    assert runner.wait(job.id, 5).outcome == "posted=False"
    with pytest.raises(Busy):
        runner.start(RENDER, "render", lambda io: "x")


def test_a_question_asked_after_stopping_is_answered_none_at_once():
    runner = JobRunner(EventBus())
    release = threading.Event()
    job = runner.start(
        BROWSER, "upload", lambda io: release.wait(5) and repr(io.choose("?", [("a", "a")]))
    )
    runner.stop()
    release.set()
    assert runner.wait(job.id, 5).outcome == "None"


def test_only_recent_jobs_are_kept_newest_first():
    runner = JobRunner(EventBus())
    for n in range(25):
        runner.wait(runner.start(RENDER, f"job {n}", lambda io: "ok").id, 5)
    recent = runner.recent()
    assert len(recent) == 20
    assert recent[0].heading == "job 24"
    with pytest.raises(ManhwatokError):
        runner.get("job1")
