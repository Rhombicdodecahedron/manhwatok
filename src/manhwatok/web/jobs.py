"""Background jobs for the web app: two lanes — renders, and uploads/logins — each running one
job at a time, questions a job waits on until a tab answers them, and the event bus every open
tab listens to. No FastAPI here: the routes start jobs and answer questions through this."""

from __future__ import annotations

import itertools
import queue
import threading
from dataclasses import dataclass, field
from typing import Callable

from manhwatok.domain.errors import ManhwatokError

RENDER, BROWSER = "render", "browser"
LANES = (RENDER, BROWSER)
KEEP_JOBS = 20  # finished jobs kept for their log, newest first


class Busy(ManhwatokError):
    """The lane already runs a job, or the app is stopping."""


class EventBus:
    """Every open tab's event stream subscribes a queue; `publish` puts (kind, data) in each."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queues: list[queue.Queue] = []

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    def publish(self, kind: str, **data) -> None:
        with self._lock:
            targets = list(self._queues)
        for q in targets:
            q.put((kind, data))


@dataclass
class Question:
    id: str
    job_id: str
    text: str
    choices: list[tuple[str, str]]  # (label, value)
    answer: str | None = None
    answered: threading.Event = field(default_factory=threading.Event, repr=False)


@dataclass
class Job:
    id: str
    lane: str
    heading: str
    log: list[str] = field(default_factory=list)
    outcome: str | None = None
    failed: bool = False
    question: Question | None = None
    done: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def running(self) -> bool:
        return not self.done.is_set()


class JobIO:
    """What a job's work gets: where it reports, and how it asks the user."""

    def __init__(self, runner: JobRunner, job: Job) -> None:
        self._runner, self._job = runner, job

    def progress(self, line: str) -> None:
        self._runner._log(self._job, line)

    def choose(self, text: str, choices: list[tuple[str, str]]) -> str | None:
        """The value of the choice the user picked; None when the app stops first."""
        return self._runner._ask(self._job, text, choices)

    def confirm(self, text: str) -> bool:
        """Yes or no; no when the app stops first."""
        return self.choose(text, [("Yes", "yes"), ("No", "no")]) == "yes"


Work = Callable[[JobIO], str]  # returns the job's closing line


class JobRunner:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}  # in start order
        self._job_ids = itertools.count(1)
        self._question_ids = itertools.count(1)
        self._stopping = False

    def start(self, lane: str, heading: str, work: Work) -> Job:
        if lane not in LANES:
            raise ValueError(f"no lane {lane!r}")
        with self._lock:
            if self._stopping:
                raise Busy("the web app is stopping")
            running = self._running(lane)
            if running is not None:
                raise Busy(f"{running.heading} is still going — try again when it's done")
            job = Job(f"job{next(self._job_ids)}", lane, heading)
            self._jobs[job.id] = job
            self._forget_old()
        self._bus.publish("job", id=job.id, lane=lane, heading=heading, state="started")
        threading.Thread(target=self._run, args=(job, work), daemon=True, name=job.id).start()
        return job

    def busy(self, lane: str) -> Job | None:
        with self._lock:
            return self._running(lane)

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ManhwatokError(f"no job {job_id} (only the last {KEEP_JOBS} are kept)")
        return job

    def recent(self) -> list[Job]:
        with self._lock:
            return list(reversed(self._jobs.values()))

    def pending(self) -> list[Question]:
        with self._lock:
            return [j.question for j in self._jobs.values() if j.question is not None]

    def answer(self, question_id: str, value: str | None) -> bool:
        """True when this answer is the one the job gets: the question is still open and
        `value` is one of its choices."""
        with self._lock:
            question = next(
                (q for q in (j.question for j in self._jobs.values()) if q and q.id == question_id),
                None,
            )
            if question is None or question.answered.is_set():
                return False
            if value not in {v for _, v in question.choices}:
                return False
            question.answer = value
            question.answered.set()
        self._bus.publish("answered", id=question_id)
        return True

    def stop(self) -> None:
        """No new jobs; every open question is answered None (no), as quitting the TUI does."""
        with self._lock:
            self._stopping = True
            open_questions = [j.question for j in self._jobs.values() if j.question is not None]
        for question in open_questions:
            question.answer = None
            question.answered.set()

    def wait(self, job_id: str, timeout: float | None = None) -> Job:
        job = self.get(job_id)
        job.done.wait(timeout)
        return job

    # --- inside a job ------------------------------------------------------------------

    def _run(self, job: Job, work: Work) -> None:
        try:
            job.outcome = work(JobIO(self, job))
        except ManhwatokError as e:
            job.outcome, job.failed = f"error: {e}", True
        except Exception as e:  # a bug ends its job with a message, never the lane
            job.outcome, job.failed = f"error: {type(e).__name__}: {e}", True
        finally:
            job.done.set()
            self._bus.publish(
                "job", id=job.id, lane=job.lane, heading=job.heading, state="finished",
                outcome=job.outcome, failed=job.failed,
            )

    def _log(self, job: Job, line: str) -> None:
        job.log.append(line)
        self._bus.publish("log", id=job.id, line=line)

    def _ask(self, job: Job, text: str, choices: list[tuple[str, str]]) -> str | None:
        with self._lock:
            if self._stopping:
                return None
            question = Question(f"q{next(self._question_ids)}", job.id, text, list(choices))
            job.question = question
        self._bus.publish(
            "question", id=question.id, job=job.id, text=text, choices=[list(c) for c in choices]
        )
        question.answered.wait()
        with self._lock:
            job.question = None
        return question.answer

    def _running(self, lane: str) -> Job | None:
        return next((j for j in self._jobs.values() if j.lane == lane and j.running), None)

    def _forget_old(self) -> None:
        finished = [j for j in self._jobs.values() if not j.running]
        while len(self._jobs) > KEEP_JOBS and finished:
            del self._jobs[finished.pop(0).id]
