# Web app, step 1: server, jobs, live updates, Posts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `manhwatok web` opens a working web app on 127.0.0.1 with the Posts page (list, full-size slides, covers, caption, render, visibility, export, delete, bulk), the upload-mode switch, background jobs and live updates.

**Architecture:** FastAPI app built by `create_app(ctx)` around the TUI's `AppContext`, calling the `app/` use cases in-process. Pages are Jinja2 templates; htmx swaps fragments; one Server-Sent Events stream per tab carries job and "data changed" events. `web/jobs.py` (no FastAPI imports) runs work in two lanes, one job at a time each.

**Tech Stack:** Python 3.12, FastAPI, Starlette `TestClient` (httpx), uvicorn, Jinja2, htmx 2 (vendored), pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-manhwatok-web-design.md` — this plan is its build-order step 1. Steps 2–5 (uploads, build/picks/art, accounts/themes, plan) get their own plans once this one has landed, since they build on the interfaces it creates.

## Global Constraints

- Bound to `127.0.0.1` only; default port `8421`; `manhwatok web --port N --no-open`.
- State-changing requests (POST/PUT/PATCH/DELETE) need an `Origin` (or `Referer`) of `http://127.0.0.1:<port>` or `http://localhost:<port>`; every request needs `Host` `127.0.0.1:<port>` or `localhost:<port>`; otherwise 403.
- Optional extra `web`: `fastapi>=0.115`, `uvicorn>=0.30`, `jinja2>=3.1`, `python-multipart>=0.0.9`. Without it: `the web app needs the web extra — run: uv sync --extra web`.
- htmx is vendored in `src/manhwatok/web/static/` — no CDN at runtime.
- The web app calls `app/` use cases, never the CLI. The TUI's behaviour does not change.
- Two job lanes, `render` and `browser`, one job at a time each; a busy lane refuses a new job with a notice.
- Expected failures (`ManhwatokError`) come back as a notice (HTTP 200, `HX-Trigger`), never a 500.
- `tests/web` files start with `pytest.importorskip("fastapi")`, like `tests/tui` does with textual.
- Code style: match the repo — docstrings that say why, `from __future__ import annotations`, 100-column lines.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

- A post deleted from the CLI/TUI while its detail is open → the detail pane says it's gone, no 500 (test in Task 7).
- A file URL with `..`, an odd name, or a symlink inside a post folder → 404, never a file outside the posts (Task 7).
- Render asked for a draft with no picks, or a post whose account was removed → the job ends with a readable error; the detail still shows (Tasks 7 and 8).
- Two tabs answering the same question → the first answer wins, the second is refused (Task 2).
- Server stopping with tabs connected → event streams end within about a second, pending questions answered no (Tasks 3 and 4).

---

## File Structure

```
src/manhwatok/app/post_view.py      NEW  post_status, scheduled_text, sent_text, caption_text (moved from tui/text.py)
src/manhwatok/tui/text.py           MOD  imports those four from app.post_view
src/manhwatok/cli.py                MOD  `web` command
pyproject.toml                      MOD  `web` extra
src/manhwatok/web/__init__.py       NEW
src/manhwatok/web/server.py         NEW  create_app(), run(), host/origin guard
src/manhwatok/web/jobs.py           NEW  EventBus, JobRunner, Job, Question, JobIO, Busy
src/manhwatok/web/events.py         NEW  sse_stream(), ChangeWatcher, change_probes(), /events route
src/manhwatok/web/routes/__init__.py NEW
src/manhwatok/web/routes/common.py  NEW  ctx_of(), page(), trigger(), done()
src/manhwatok/web/routes/header.py  NEW  POST /mode, GET /busy
src/manhwatok/web/routes/posts.py   NEW  Posts page, table, detail, actions, bulk
src/manhwatok/web/routes/files.py   NEW  GET /files/{post_id}/{name}
src/manhwatok/web/templates/        NEW  base.html, _header.html, _busy.html, posts.html,
                                         _posts_table.html, _post_detail.html, _post_gone.html
src/manhwatok/web/static/           NEW  htmx.min.js (vendored), app.js, app.css
tests/unit/test_post_view.py        NEW
tests/web/__init__.py, conftest.py, helpers.py   NEW
tests/web/test_server.py, test_jobs.py, test_events.py, test_header.py, test_posts.py, test_files.py  NEW
README.md                           MOD  "Web app" section
```

---

### Task 1: Move the post view helpers out of the TUI

**Files:**
- Create: `src/manhwatok/app/post_view.py`
- Modify: `src/manhwatok/tui/text.py` (remove the four functions, import them)
- Test: `tests/unit/test_post_view.py`

**Interfaces:**
- Produces: `manhwatok.app.post_view.post_status(post: ListPost, posts: PostRepository) -> str` (one of `"sent"`, `"exported"`, `"draft"`, `"not rendered"`, `"rendered"`), `scheduled_text(post, zone: str) -> str`, `sent_text(post, zone: str) -> str`, `caption_text(post, posts) -> tuple[str, bool]` — unchanged behaviour.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_post_view.py`:
```python
"""The post view helpers live in app/ so the TUI and the web app share them."""

from datetime import datetime, timezone

from manhwatok.app import post_view
from manhwatok.app.render_post import render_post
from manhwatok.tui import text
from tests.unit.fakes import make_tools, post


def test_the_tui_uses_the_shared_helpers():
    for name in ("post_status", "scheduled_text", "sent_text", "caption_text"):
        assert getattr(text, name) is getattr(post_view, name)


def test_post_status_follows_the_post(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(id="20260926-0001"))
    fresh = tools.posts.get("20260926-0001")
    assert post_view.post_status(fresh, tools.posts) == "not rendered"
    render_post(fresh.id, tools)
    assert post_view.post_status(fresh, tools.posts) == "rendered"
    sent = fresh.model_copy(update={"sent_at": datetime(2026, 9, 26, tzinfo=timezone.utc)})
    assert post_view.post_status(sent, tools.posts) == "sent"
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_post_view.py -v`
Expected: FAIL — `ImportError: cannot import name 'post_view'`.

- [ ] **Step 3: Move the code**

Create `src/manhwatok/app/post_view.py` with the exact bodies of `post_status`, `scheduled_text`, `sent_text` and `caption_text` cut from `src/manhwatok/tui/text.py`:
```python
"""How a post reads in a list or a detail view: its status, when it goes out, its caption.
Shared by the TUI and the web app."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from manhwatok.app.render_post import rendered_files
from manhwatok.domain.caption import build_caption
from manhwatok.domain.errors import NotRendered, StorageError
from manhwatok.domain.post import ListPost
from manhwatok.ports.posts import PostRepository


def post_status(post: ListPost, posts: PostRepository) -> str:
    if post.sent_at:
        return "sent"
    if post.exported_at:
        return "exported"
    if post.is_unfinished:
        return "draft"
    try:
        rendered_files(post, posts)
    except NotRendered:
        return "not rendered"
    return "rendered"


def scheduled_text(post: ListPost, zone: str) -> str:
    """When the post goes out, short ("Thu 19:00"), in time zone `zone`; "-" when unscheduled."""
    if post.scheduled_at is None:
        return "-"
    return f"{post.scheduled_at.astimezone(ZoneInfo(zone)):%a %H:%M}"


def sent_text(post: ListPost, zone: str) -> str:
    """The day the post went out, short ("18 Sep"), in time zone `zone`; "-" when unsent."""
    if post.sent_at is None:
        return "-"
    return f"{post.sent_at.astimezone(ZoneInfo(zone)):%d %b}"


def caption_text(post: ListPost, posts: PostRepository) -> tuple[str, bool]:
    """(caption, rendered): caption.txt as rendered, else the caption the post would get."""
    try:
        _, caption = rendered_files(post, posts)
        return caption.read_text(encoding="utf-8").rstrip("\n"), True
    except (NotRendered, OSError, UnicodeDecodeError, StorageError):
        return build_caption(post), False
```
In `src/manhwatok/tui/text.py`, delete those four functions and replace the imports they used with:
```python
from manhwatok.app.post_view import caption_text, post_status, scheduled_text, sent_text  # noqa: F401
```
Keep the imports `post_details` and `clip` still need (`chapter_label`, `post_emojis`, `AUTO`, `ArtStyle`, `CoverStyle`, `plain_title`, `ListPost`, `PostRepository`); drop `ZoneInfo`, `rendered_files`, `build_caption`, `NotRendered`, `StorageError` if nothing else in the file uses them.

- [ ] **Step 4: Run the new test and the TUI tests**

Run: `uv run pytest tests/unit/test_post_view.py tests/tui -q`
Expected: all PASS (the TUI tests prove nothing changed there).

- [ ] **Step 5: Commit**

```bash
git add src/manhwatok/app/post_view.py src/manhwatok/tui/text.py tests/unit/test_post_view.py
git commit -m "refactor: move post view helpers into app/ for the web app to share"
```

---

### Task 2: Job lanes, questions and the event bus

**Files:**
- Modify: `pyproject.toml` (the `web` extra)
- Create: `src/manhwatok/web/__init__.py`, `src/manhwatok/web/jobs.py`
- Create: `tests/web/__init__.py`, `tests/web/conftest.py`
- Test: `tests/web/test_jobs.py`

**Interfaces:**
- Produces:
  - `RENDER = "render"`, `BROWSER = "browser"`, `LANES = (RENDER, BROWSER)`.
  - `class Busy(ManhwatokError)`.
  - `EventBus`: `subscribe() -> queue.Queue` (items are `(kind: str, data: dict)`), `unsubscribe(q)`, `publish(kind: str, **data)`.
  - `Question` dataclass: `id: str`, `job_id: str`, `text: str`, `choices: list[tuple[str, str]]` (label, value), `answer: str | None`.
  - `Job` dataclass: `id`, `lane`, `heading`, `log: list[str]`, `outcome: str | None`, `failed: bool`, `question: Question | None`, property `running: bool`.
  - `JobIO`: `progress(line: str)`, `choose(text: str, choices: list[tuple[str, str]]) -> str | None`, `confirm(text: str) -> bool`.
  - `JobRunner(bus)`: `start(lane, heading, work: Callable[[JobIO], str]) -> Job` (raises `Busy`), `busy(lane) -> Job | None`, `get(job_id) -> Job` (raises `ManhwatokError`), `recent() -> list[Job]` (newest first), `pending() -> list[Question]`, `answer(question_id, value: str | None) -> bool`, `stop()`, `wait(job_id, timeout) -> Job`.
  - Events published: `("job", {id, lane, heading, state: "started"|"finished", outcome?, failed?})`, `("log", {id, line})`, `("question", {id, job, text, choices})`, `("answered", {id})`.

- [ ] **Step 0: Add the `web` extra and the test scaffolding**

In `pyproject.toml` under `[project.optional-dependencies]`, after `phone = [...]`:
```toml
web = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
]
```
Run: `uv sync --extra upload --extra tui --extra pinterest --extra phone --extra web`
Expected: installs fastapi, uvicorn, jinja2, python-multipart.

`tests/web/__init__.py`: empty.

`tests/web/conftest.py`:
```python
import pytest

from tests.tui.helpers import OPEN_CONTEXTS


@pytest.fixture(autouse=True)
def _never_the_real_data_dir(tmp_path, monkeypatch):
    """Anything that builds Settings() by itself lands in a temporary folder."""
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path / "default-data"))
    monkeypatch.setenv("MANHWATOK_EXPORT_DIR", str(tmp_path / "default-exports"))


@pytest.fixture(autouse=True)
def _close_contexts():
    yield
    while OPEN_CONTEXTS:
        OPEN_CONTEXTS.pop().close()
```

`src/manhwatok/web/__init__.py`:
```python
"""The web front end (`manhwatok web`); needs the `web` extra."""
```

- [ ] **Step 1: Write the failing tests**

`tests/web/test_jobs.py`:
```python
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
    job = runner.start(BROWSER, "upload", lambda io: f"chose {io.choose('Sound?', [('A', 'a'), ('none', '')])}")
    question = _pending(runner)
    assert (question.text, question.choices, question.job_id) == ("Sound?", [("A", "a"), ("none", "")], job.id)
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
    job = runner.start(BROWSER, "upload", lambda io: release.wait(5) and repr(io.choose("?", [("a", "a")])))
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
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.web'` (or `.jobs`).

- [ ] **Step 3: Write `jobs.py`**

`src/manhwatok/web/jobs.py`:
```python
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/web/test_jobs.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/manhwatok/web/__init__.py src/manhwatok/web/jobs.py tests/web/__init__.py tests/web/conftest.py tests/web/test_jobs.py
git commit -m "feat(web): job lanes, questions a job waits on, and the event bus"
```

---

### Task 3: `manhwatok web` and the server skeleton with its guard

**Files:**
- Modify: `src/manhwatok/cli.py` (command after `tui`)
- Create: `src/manhwatok/web/server.py`, `src/manhwatok/web/routes/__init__.py`
- Create: `tests/web/helpers.py`, `tests/web/test_server.py`

**Interfaces:**
- Produces: `create_app(ctx: AppContext, *, port: int = 8421, clock: Callable[[], datetime] = <utc now>, watch_interval: float | None = 2.0) -> FastAPI` with `app.state.ctx`, `app.state.bus`, `app.state.jobs`, `app.state.stop` (`threading.Event`), `app.state.clock`, `app.state.templates`. `run(settings: Settings, port: int = 8421, open_browser: bool = True) -> None`. `DEFAULT_PORT = 8421`.
- Produces (tests): `tests.web.helpers.BASE = "http://127.0.0.1:8421"`, `client_for(ctx, **create_kwargs) -> TestClient` (lifespan entered; default headers carry `Origin: BASE`), `wait_job(client: TestClient, job_id: str, timeout: float = 5.0) -> Job`.
- Consumes: `JobRunner`, `EventBus` (Task 2).

- [ ] **Step 1: Write the failing tests**

`tests/web/helpers.py`:
```python
"""Driving the web app in tests: a TestClient on a context of fakes (tests.tui.helpers)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.tui.helpers import NOW

BASE = "http://127.0.0.1:8421"


def client_for(ctx, **create_kwargs) -> TestClient:
    """A client whose requests come from the app's own page. Use it as a context manager so the
    app's startup and shutdown run: `with client_for(ctx) as client:`."""
    from manhwatok.web.server import create_app

    create_kwargs.setdefault("watch_interval", None)
    create_kwargs.setdefault("clock", lambda: NOW)
    app = create_app(ctx, **create_kwargs)
    return TestClient(app, base_url=BASE, headers={"Origin": BASE})


def wait_job(client: TestClient, job_id: str, timeout: float = 5.0):
    job = client.app.state.jobs.wait(job_id, timeout)
    assert not job.running, f"{job.heading} still running"
    return job
```

`tests/web/test_server.py`:
```python
import pytest

pytest.importorskip("fastapi")

from typer.testing import CliRunner  # noqa: E402

from manhwatok.cli import app as cli  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.web.helpers import BASE, client_for  # noqa: E402


def _with_echo(client):
    client.app.add_api_route("/echo", lambda: {"ok": True}, methods=["POST"])
    return client


def test_home_goes_to_posts(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/posts"


def test_a_post_from_the_app_itself_passes(tmp_path):
    with _with_echo(client_for(make_ctx(tmp_path))) as client:
        assert client.post("/echo").status_code == 200
        referer_only = {"Origin": "", "Referer": f"{BASE}/posts"}
        assert client.post("/echo", headers=referer_only).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "", "Referer": "https://evil.example/page"},
        {"Origin": ""},  # neither
        {"Origin": "http://127.0.0.1:9999"},  # another port on this computer
    ],
)
def test_a_post_from_anywhere_else_is_refused(tmp_path, headers):
    with _with_echo(client_for(make_ctx(tmp_path))) as client:
        assert client.post("/echo", headers=headers).status_code == 403


def test_a_request_for_another_host_is_refused(tmp_path):
    """DNS rebinding: a page on some domain that resolves to 127.0.0.1."""
    with client_for(make_ctx(tmp_path)) as client:
        response = client.get("/", headers={"Host": "evil.example:8421"})
    assert response.status_code == 403


def test_web_command_without_the_extra_says_how_to_install(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "fastapi", None)
    result = CliRunner().invoke(cli, ["web", "--no-open"])
    assert result.exit_code == 1
    assert "the web app needs the web extra — run: uv sync --extra web" in result.output


def test_web_command_runs_the_server(monkeypatch):
    import manhwatok.web.server as server

    calls = []
    monkeypatch.setattr(server, "run", lambda settings, port, open_browser: calls.append(
        (port, open_browser)))
    result = CliRunner().invoke(cli, ["web", "--port", "9000", "--no-open"])
    assert result.exit_code == 0
    assert calls == [(9000, False)]
```
(`_fail` in `cli.py` exits with code 1; check `grep -n "def _fail" -A6 src/manhwatok/cli.py` and adjust the expected code if it differs.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.web'`.

- [ ] **Step 3: Write the server and the command**

`src/manhwatok/web/routes/__init__.py`:
```python
"""One module per page; each has a `router`."""
```
`src/manhwatok/web/server.py`:
```python
"""The manhwatok web app: FastAPI on 127.0.0.1, pages rendered on the server, htmx in the page.

It can publish to TikTok, so it only answers this computer: requests must be addressed to
127.0.0.1/localhost on its port (no DNS rebinding), and anything that changes something must come
from its own pages (no other website open in the same browser can post to it)."""

from __future__ import annotations

import threading
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from manhwatok.app.context import AppContext, open_context
from manhwatok.config import Settings
from manhwatok.web.jobs import EventBus, JobRunner

HERE = Path(__file__).parent
DEFAULT_PORT = 8421
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else None


def create_app(
    ctx: AppContext,
    *,
    port: int = DEFAULT_PORT,
    clock: Callable[[], datetime] = _utc_now,
    watch_interval: float | None = 2.0,
) -> FastAPI:
    """The app around an open `ctx` (the caller closes it). `watch_interval`: how often to look
    for changes made elsewhere (CLI, TUI); None never looks (tests)."""
    bus = EventBus()
    jobs = JobRunner(bus)
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        stop.set()  # event streams end
        jobs.stop()  # questions answered no, no new jobs

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx
    app.state.bus = bus
    app.state.jobs = jobs
    app.state.stop = stop
    app.state.clock = clock
    app.state.templates = Jinja2Templates(directory=HERE / "templates")

    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    hosts = {origin.split("//", 1)[1] for origin in origins}

    @app.middleware("http")
    async def only_this_computer(request: Request, call_next):
        if request.headers.get("host") not in hosts:
            return PlainTextResponse("this app only answers 127.0.0.1", status_code=403)
        if request.method in UNSAFE:
            origin = request.headers.get("origin") or _origin_of(
                request.headers.get("referer", "")
            )
            if origin not in origins:
                return PlainTextResponse("not from this app's pages", status_code=403)
        return await call_next(request)

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.get("/")
    def home() -> RedirectResponse:
        return RedirectResponse("/posts", status_code=303)

    return app


def run(settings: Settings, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    """Serve the app on 127.0.0.1:`port` until Ctrl-C. Open event streams are cut after two
    seconds on the way out, so Ctrl-C doesn't wait on the tabs."""
    import uvicorn

    ctx = open_context(settings)
    try:
        app = create_app(ctx, port=port)
        url = f"http://127.0.0.1:{port}/"
        if open_browser:
            threading.Timer(1.0, webbrowser.open, (url,)).start()
        print(f"manhwatok web on {url} — Ctrl-C stops it")
        uvicorn.run(
            app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=2
        )
    finally:
        ctx.close()
```
Create `src/manhwatok/web/static/` and `src/manhwatok/web/templates/` now with a `.gitkeep` each, so `StaticFiles` finds its directory (Task 5 fills them).

In `src/manhwatok/cli.py`, right after the `tui` command:
```python
@app.command()
def web(
    port: int = typer.Option(8421, "--port", help="The port on 127.0.0.1."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open it in the browser."),
) -> None:
    """Open the web app on this computer: posts with full-size slides, uploads you can watch."""
    try:
        import fastapi  # noqa: F401
        import jinja2  # noqa: F401
        import multipart  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        _fail(ManhwatokError("the web app needs the web extra — run: uv sync --extra web"))
    from manhwatok.web.server import run

    try:
        run(Settings(), port=port, open_browser=open_browser)
    except ManhwatokError as e:
        _fail(e)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/web/test_server.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/manhwatok/cli.py src/manhwatok/web tests/web
git commit -m "feat(web): manhwatok web — a FastAPI app that only answers this computer"
```

---

### Task 4: Event stream and the change watcher

**Files:**
- Create: `src/manhwatok/web/events.py`
- Modify: `src/manhwatok/web/server.py` (watcher in the lifespan, include the router)
- Test: `tests/web/test_events.py`

**Interfaces:**
- Consumes: `EventBus` (Task 2); `app.state.bus`, `app.state.stop` (Task 3).
- Produces: `sse_stream(bus: EventBus, stop: threading.Event, heartbeat: float = 15.0) -> Iterator[str]`; `ChangeWatcher(bus, probes: dict[str, Callable[[], object]], interval: float)` with `check() -> list[str]`, `start()`, `stop()`; `change_probes(ctx: AppContext) -> dict[str, Callable[[], object]]` with keys `"posts"` and `"store"`; `router` with `GET /events`. Event `("changed", {"what": "posts" | "store"})`.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_events.py`:
```python
import json
import threading
import time

import pytest

pytest.importorskip("fastapi")

from manhwatok.web.events import ChangeWatcher, change_probes, sse_stream  # noqa: E402
from manhwatok.web.jobs import EventBus  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import post  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402


def test_the_stream_sends_events_and_pings_and_ends_when_stopped():
    bus, stop = EventBus(), threading.Event()
    stream = sse_stream(bus, stop, heartbeat=0.05)
    assert next(stream) == "retry: 2000\n\n"
    bus.publish("changed", what="posts")
    assert next(stream) == f"event: changed\ndata: {json.dumps({'what': 'posts'})}\n\n"
    assert next(stream) == ": ping\n\n"  # nothing for a while
    stop.set()
    started = time.monotonic()
    with pytest.raises(StopIteration):
        while True:
            next(stream)
    assert time.monotonic() - started < 1.5  # the server's Ctrl-C isn't kept waiting
    assert bus._queues == []  # unsubscribed


def test_the_events_route_streams(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        client.app.state.stop.set()  # the stream ends after its first line
        response = client.get("/events")
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.startswith("retry: 2000")


def test_the_watcher_says_what_changed():
    bus = EventBus()
    q = bus.subscribe()
    values = {"posts": 1, "store": "a"}

    def store():
        if values["store"] is None:
            raise OSError("gone")
        return values["store"]

    watcher = ChangeWatcher(bus, {"posts": lambda: values["posts"], "store": store}, interval=1)
    assert watcher.check() == []  # the first look only remembers
    values["posts"] = 2
    assert watcher.check() == ["posts"]
    assert q.get_nowait() == ("changed", {"what": "posts"})
    values["store"] = None  # a probe that fails counts as a change once
    assert watcher.check() == ["store"]
    assert watcher.check() == []


def test_the_watcher_looks_in_the_background():
    bus = EventBus()
    q = bus.subscribe()
    values = {"posts": 1}
    watcher = ChangeWatcher(bus, {"posts": lambda: values["posts"]}, interval=0.01)
    watcher.start()
    try:
        values["posts"] = 2
        assert q.get(timeout=2) == ("changed", {"what": "posts"})
    finally:
        watcher.stop()


def test_probes_see_a_new_post_and_a_database_write(tmp_path):
    ctx = make_ctx(tmp_path)
    probes = change_probes(ctx)
    before = {name: probe() for name, probe in probes.items()}
    ctx.tools.posts.save(post(id="20260926-0001"))
    assert probes["posts"]() != before["posts"]
    from manhwatok.domain.account import Account

    time.sleep(0.01)
    ctx.store.accounts.add(Account(handle="reads"))
    assert probes["store"]() != before["store"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.web.events'`.

- [ ] **Step 3: Write `events.py` and wire it in**

`src/manhwatok/web/events.py`:
```python
"""Live updates: one Server-Sent Events stream per tab, carrying what the event bus publishes,
and a watcher that notices changes made elsewhere (the CLI, the TUI) and publishes them too."""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from manhwatok.app.context import AppContext
from manhwatok.web.jobs import EventBus

router = APIRouter()


def sse_stream(bus: EventBus, stop: threading.Event, heartbeat: float = 15.0) -> Iterator[str]:
    """The stream's lines: events as they come, a ping after `heartbeat` quiet seconds (so a
    dead tab is noticed), and the end within a second of `stop`."""
    q = bus.subscribe()
    try:
        yield "retry: 2000\n\n"
        quiet_since = time.monotonic()
        while not stop.is_set():
            try:
                kind, data = q.get(timeout=min(1.0, heartbeat))
            except queue.Empty:
                if time.monotonic() - quiet_since >= heartbeat:
                    quiet_since = time.monotonic()
                    yield ": ping\n\n"
                continue
            quiet_since = time.monotonic()
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"
    finally:
        bus.unsubscribe(q)


@router.get("/events")
def events(request: Request) -> StreamingResponse:
    state = request.app.state
    return StreamingResponse(
        sse_stream(state.bus, state.stop),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )


class ChangeWatcher:
    """Looks at each probe every `interval` seconds and publishes ("changed", {"what": name})
    when its value differs from the last look. A probe raising OSError reads as None."""

    def __init__(
        self, bus: EventBus, probes: dict[str, Callable[[], object]], interval: float
    ) -> None:
        self._bus, self._probes, self._interval = bus, probes, interval
        self._last: dict[str, object] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check(self) -> list[str]:
        changed = []
        for name, probe in self._probes.items():
            try:
                value = probe()
            except OSError:
                value = None
            if name in self._last and self._last[name] != value:
                changed.append(name)
            self._last[name] = value
        for name in changed:
            self._bus.publish("changed", what=name)
        return changed

    def start(self) -> None:
        self.check()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="change-watcher")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.check()


def _mtimes(db: Path) -> tuple:
    """The database and its write-ahead log: SQLite writes the log first."""
    wal = db.with_name(db.name + "-wal")
    return tuple(p.stat().st_mtime_ns if p.exists() else None for p in (db, wal))


def change_probes(ctx: AppContext) -> dict[str, Callable[[], object]]:
    return {
        "posts": ctx.tools.posts.stamp,
        "store": lambda: _mtimes(ctx.settings.db_path),
    }
```
In `src/manhwatok/web/server.py`:
- import: `from manhwatok.web import events`
- in `create_app`, before `lifespan`: 
```python
    watcher = (
        events.ChangeWatcher(bus, events.change_probes(ctx), watch_interval)
        if watch_interval
        else None
    )
```
- make `lifespan`:
```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if watcher is not None:
            watcher.start()
        yield
        stop.set()  # event streams end
        jobs.stop()  # questions answered no, no new jobs
        if watcher is not None:
            watcher.stop()
```
- after `app.mount(...)`: `app.include_router(events.router)`

Check that `make_ctx` gives a real SQLite database at `ctx.settings.db_path` (`tmp_path / "manhwatok.db"` — `Settings(data_dir=tmp_path)` and `SqliteStore(tmp_path / "manhwatok.db")` agree). If the `store` probe test fails because the write went only to the WAL within the same mtime tick, keep the `time.sleep(0.01)`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/web -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/manhwatok/web/events.py src/manhwatok/web/server.py tests/web/test_events.py
git commit -m "feat(web): live event stream and a watcher for changes made elsewhere"
```

---

### Task 5: Layout, static files and the upload-mode switch

**Files:**
- Create: `src/manhwatok/web/routes/common.py`, `src/manhwatok/web/routes/header.py`
- Create: `src/manhwatok/web/templates/base.html`, `_header.html`, `_busy.html`
- Create: `src/manhwatok/web/static/htmx.min.js` (download), `app.js`, `app.css` (remove the `.gitkeep` files)
- Modify: `src/manhwatok/web/server.py` (include `header.router`)
- Test: `tests/web/test_header.py`

**Interfaces:**
- Consumes: `app.state.*` (Task 3), `LANES`, `Busy` (Task 2), `AppContext.upload_mode`, `.upload_mode_label`, `.set_upload_mode`, `UPLOAD_MODE_LABELS` (`manhwatok.app.context`).
- Produces (`routes/common.py`):
  - `ctx_of(request) -> AppContext`
  - `page(request, name: str, **context) -> HTMLResponse` — renders a template with `mode`, `modes` (list of (value, label)), `busy` (list of running `Job`) added.
  - `trigger(response, text: str | None = None, level: str = "info", changed: Iterable[str] = ()) -> Response` — sets `HX-Trigger` to `{"notice": {"text", "level"}, "changed-<what>": true, ...}`.
  - `done(request, text, level="info", changed=()) -> Response` — an empty 200 with `trigger(...)`, and `bus.publish("changed", what=...)` for each `changed` so other tabs refresh too.
- Page contract for later tasks: templates extend `base.html` and fill `{% block content %}`; set `page` in the context to the sidebar key (`"posts"`); a fragment that must refresh when posts change uses `hx-trigger="changed-posts from:body"`; buttons that only notify use `hx-swap="none"`.
- JS contract: every SSE event becomes a DOM event on `<body>` with the same name (`changed-<what>` for "changed"), with the event's data as `detail`; `notice` events show a toast; a finished `job` event shows its outcome as a toast; elements with `data-slide` inside a `[data-gallery]` open in the lightbox.

- [ ] **Step 1: Vendor htmx**

Run:
```bash
curl -fsSL https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js -o src/manhwatok/web/static/htmx.min.js
head -c 120 src/manhwatok/web/static/htmx.min.js; echo; wc -c src/manhwatok/web/static/htmx.min.js
rm -f src/manhwatok/web/static/.gitkeep src/manhwatok/web/templates/.gitkeep
```
Expected: the file starts with `var htmx=function()` (or similar minified header) and is roughly 50 KB. htmx is BSD-2-Clause (0BSD for 2.x); keep the file as downloaded.

- [ ] **Step 2: Write the failing tests**

`tests/web/test_header.py`:
```python
import json
import threading

import pytest

pytest.importorskip("fastapi")

from manhwatok.web.jobs import RENDER  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402


def _notice(response) -> dict:
    return json.loads(response.headers["HX-Trigger"])["notice"]


def test_the_mode_switch_changes_how_uploads_go(tmp_path):
    ctx = make_ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post("/mode", data={"mode": "phone-post"})
    assert response.status_code == 200
    assert ctx.upload_mode == "phone-post"
    assert 'value="phone-post" selected' in response.text
    assert _notice(response) == {
        "text": "uploads and logins now go through the phone, posting and sharing to the Story",
        "level": "info",
    }


def test_an_unknown_mode_changes_nothing(tmp_path):
    ctx = make_ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post("/mode", data={"mode": "fax"})
    assert ctx.upload_mode == "browser"
    assert _notice(response)["level"] == "error"


def test_busy_shows_what_runs(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        assert "idle" in client.get("/busy").text
        release = threading.Event()
        job = client.app.state.jobs.start(RENDER, "render post x", lambda io: release.wait(5) and "ok")
        assert "render post x" in client.get("/busy").text
        release.set()
        client.app.state.jobs.wait(job.id, 5)


def test_static_files_are_served(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        for name in ("htmx.min.js", "app.js", "app.css"):
            assert client.get(f"/static/{name}").status_code == 200
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/web/test_header.py -v`
Expected: FAIL — 404 on `/mode` and `/busy`, and on `/static/app.js`.

- [ ] **Step 4: Write the helpers, the route, the templates and the static files**

`src/manhwatok/web/routes/common.py`:
```python
"""What every route needs: the context, rendering a page or fragment with the header's data,
and telling the page what happened (a notice) and what changed (so it refreshes)."""

from __future__ import annotations

import json
from typing import Iterable

from fastapi import Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.app.context import UPLOAD_MODE_LABELS, AppContext
from manhwatok.web.jobs import LANES


def ctx_of(request: Request) -> AppContext:
    return request.app.state.ctx


def page(request: Request, name: str, **context) -> HTMLResponse:
    ctx = ctx_of(request)
    jobs = request.app.state.jobs
    base = {
        "mode": ctx.upload_mode,
        "modes": list(UPLOAD_MODE_LABELS.items()),
        "busy": [job for lane in LANES if (job := jobs.busy(lane)) is not None],
    }
    return request.app.state.templates.TemplateResponse(request, name, {**base, **context})


def trigger(
    response: Response,
    text: str | None = None,
    level: str = "info",
    changed: Iterable[str] = (),
) -> Response:
    """htmx fires these on the page: `notice` shows a toast, `changed-<what>` refreshes."""
    events: dict = {f"changed-{what}": True for what in changed}
    if text is not None:
        events["notice"] = {"text": text, "level": level}
    if events:
        response.headers["HX-Trigger"] = json.dumps(events)
    return response


def done(
    request: Request, text: str, level: str = "info", changed: Iterable[str] = ()
) -> Response:
    """An empty answer for a button that only reports; other tabs hear about `changed` too."""
    changed = list(changed)
    for what in changed:
        request.app.state.bus.publish("changed", what=what)
    return trigger(Response(status_code=200), text, level, changed)
```

`src/manhwatok/web/routes/header.py`:
```python
"""The header: how uploads go (as the TUI's `b`), and what is running."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from manhwatok.domain.errors import ManhwatokError
from manhwatok.web.routes.common import ctx_of, page, trigger

router = APIRouter()


@router.post("/mode", response_class=HTMLResponse)
def set_mode(request: Request, mode: str = Form(...)) -> HTMLResponse:
    ctx = ctx_of(request)
    try:
        ctx.set_upload_mode(mode)
    except ManhwatokError as e:
        return trigger(page(request, "_header.html"), str(e), "error")
    text = f"uploads and logins now go through the {ctx.upload_mode_label}"
    return trigger(page(request, "_header.html"), text)


@router.get("/busy", response_class=HTMLResponse)
def busy(request: Request) -> HTMLResponse:
    return page(request, "_busy.html")
```

`src/manhwatok/web/templates/base.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}manhwatok{% endblock %}</title>
  <link rel="stylesheet" href="/static/app.css">
  <script src="/static/htmx.min.js" defer></script>
  <script src="/static/app.js" defer></script>
</head>
<body>
  <nav class="sidebar">
    <a class="brand" href="/">manhwatok</a>
    <a href="/posts" {% if page == "posts" %}aria-current="page"{% endif %}>Posts</a>
  </nav>
  <div class="main">
    <header id="header" class="header">{% include "_header.html" %}</header>
    <main>{% block content %}{% endblock %}</main>
  </div>
  <div id="toasts" aria-live="polite"></div>
  <dialog id="lightbox">
    <img alt="">
    <button type="button" class="prev" aria-label="Previous slide">‹</button>
    <button type="button" class="next" aria-label="Next slide">›</button>
    <button type="button" class="close" aria-label="Close">✕</button>
  </dialog>
</body>
</html>
```

`src/manhwatok/web/templates/_header.html`:
```html
<form class="mode" hx-post="/mode" hx-trigger="change" hx-target="#header">
  <label>Upload via
    <select name="mode">
      {% for value, label in modes %}
      <option value="{{ value }}" {% if value == mode %}selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
  </label>
</form>
<div id="busy" hx-get="/busy" hx-trigger="job from:body">{% include "_busy.html" %}</div>
```
Note: the test looks for `value="phone-post" selected` — keep exactly one space between `"{{ value }}"` and `selected`.

`src/manhwatok/web/templates/_busy.html`:
```html
{% for job in busy %}<span class="busy">{{ job.heading }}…</span>{% else %}<span class="idle">idle</span>{% endfor %}
```

`src/manhwatok/web/static/app.js`:
```js
// manhwatok web: live updates, toasts, the slide lightbox. htmx does everything else.
(() => {
  const body = document.body;

  // One event stream per tab; each event becomes a DOM event on <body> that htmx
  // attributes can listen to (hx-trigger="changed-posts from:body").
  const source = new EventSource("/events");
  source.addEventListener("changed", (e) => {
    htmx.trigger(body, "changed-" + JSON.parse(e.data).what);
  });
  for (const kind of ["job", "log", "question", "answered"]) {
    source.addEventListener(kind, (e) => htmx.trigger(body, kind, JSON.parse(e.data)));
  }

  // Toasts: from HX-Trigger {"notice": {...}} and from finished jobs.
  const toasts = document.getElementById("toasts");
  function toast(text, level) {
    const div = document.createElement("div");
    div.className = "toast " + (level || "info");
    div.textContent = text;
    toasts.append(div);
    setTimeout(() => div.remove(), level === "error" ? 10000 : 5000);
  }
  body.addEventListener("notice", (e) => toast(e.detail.text, e.detail.level));
  body.addEventListener("job", (e) => {
    if (e.detail.state === "finished") toast(e.detail.outcome, e.detail.failed ? "error" : "info");
  });

  // Lightbox: click a [data-slide] image; ← → step through its [data-gallery].
  const box = document.getElementById("lightbox");
  const big = box.querySelector("img");
  let slides = [];
  let at = 0;
  function show(n) {
    at = (n + slides.length) % slides.length;
    big.src = slides[at].dataset.full || slides[at].src;
  }
  document.addEventListener("click", (e) => {
    const slide = e.target.closest("[data-slide]");
    if (!slide) return;
    slides = [...slide.closest("[data-gallery]").querySelectorAll("[data-slide]")];
    show(slides.indexOf(slide));
    box.showModal();
  });
  box.querySelector(".prev").addEventListener("click", () => show(at - 1));
  box.querySelector(".next").addEventListener("click", () => show(at + 1));
  box.querySelector(".close").addEventListener("click", () => box.close());
  box.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") show(at - 1);
    if (e.key === "ArrowRight") show(at + 1);
  });
})();
```

`src/manhwatok/web/static/app.css`:
```css
:root {
  --bg: #f6f6f8; --panel: #ffffff; --text: #1b1b1f; --muted: #6b6b76;
  --line: #e2e2e8; --accent: #1f8fbf; --danger: #c0392b; --warn: #b7791f;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #131316; --panel: #1c1c21; --text: #ececf1; --muted: #9a9aa6;
          --line: #2c2c34; --accent: #43c9e4; --danger: #ff6b5b; --warn: #f0b429; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
       font: 14px/1.45 system-ui, sans-serif; display: grid; grid-template-columns: 180px 1fr;
       min-height: 100vh; }
.sidebar { background: var(--panel); border-right: 1px solid var(--line); padding: 16px 0;
           display: flex; flex-direction: column; }
.sidebar a { color: var(--text); text-decoration: none; padding: 8px 20px; }
.sidebar a[aria-current="page"] { background: var(--bg); border-left: 3px solid var(--accent); }
.sidebar .brand { font-weight: 700; margin-bottom: 12px; }
.main { min-width: 0; }
.header { display: flex; gap: 24px; align-items: center; padding: 10px 20px;
          border-bottom: 1px solid var(--line); background: var(--panel); }
.header .busy { color: var(--warn); }
.header .idle { color: var(--muted); }
main { padding: 16px 20px; }
button, select, input { font: inherit; }
button { border: 1px solid var(--line); background: var(--panel); color: var(--text);
         border-radius: 6px; padding: 5px 12px; cursor: pointer; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.danger { color: var(--danger); }
table { border-collapse: collapse; width: 100%; background: var(--panel); }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); }
tr.selected td { background: var(--bg); }
td.link { cursor: pointer; color: var(--accent); }
.status { font-size: 12px; padding: 1px 8px; border-radius: 10px; background: var(--bg); }
.posts { display: grid; grid-template-columns: minmax(420px, 2fr) 3fr; gap: 16px; }
.filters { display: flex; gap: 12px; margin-bottom: 10px; align-items: center; }
.detail { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
          padding: 14px; min-height: 200px; }
.slides { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 6px; }
.slides img { height: 360px; border-radius: 6px; cursor: zoom-in; }
.covers { display: flex; gap: 10px; }
.covers figure { margin: 0; text-align: center; }
.covers img { height: 180px; border-radius: 6px; border: 3px solid transparent; cursor: pointer; }
.covers .chosen img { border-color: var(--accent); }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.caption { white-space: pre-wrap; background: var(--bg); padding: 10px; border-radius: 6px; }
.muted { color: var(--muted); }
#toasts { position: fixed; right: 16px; bottom: 16px; display: flex; flex-direction: column;
          gap: 8px; z-index: 10; }
.toast { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--accent);
         padding: 8px 12px; border-radius: 6px; max-width: 420px; }
.toast.error { border-left-color: var(--danger); }
.toast.warning { border-left-color: var(--warn); }
#lightbox { border: 0; background: transparent; padding: 0; }
#lightbox::backdrop { background: rgba(0, 0, 0, .85); }
#lightbox img { max-height: 92vh; max-width: 92vw; display: block; }
#lightbox button { position: fixed; top: 50%; background: rgba(0,0,0,.5); color: #fff; border: 0;
                   font-size: 28px; }
#lightbox .prev { left: 20px; } #lightbox .next { right: 20px; }
#lightbox .close { top: 20px; right: 20px; }
```

In `src/manhwatok/web/server.py`: `from manhwatok.web.routes import header` and, after `app.include_router(events.router)`, `app.include_router(header.router)`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/web -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/manhwatok/web tests/web/test_header.py
git commit -m "feat(web): layout, live updates in the page, and the upload-mode switch"
```

---

### Task 6: The Posts page and its table

**Files:**
- Create: `src/manhwatok/web/routes/posts.py`
- Create: `src/manhwatok/web/templates/posts.html`, `_posts_table.html`
- Modify: `src/manhwatok/web/server.py` (include `posts.router`)
- Test: `tests/web/test_posts.py`

**Interfaces:**
- Consumes: `page`, `ctx_of` (Task 5); `post_status`, `scheduled_text`, `sent_text` (Task 1); `DEFAULT_TIMEZONE` (`manhwatok.domain.account`).
- Produces: `STATUSES = ("draft", "not rendered", "rendered", "exported", "sent")`; `NO_ACCOUNT = "none"` (the account filter's value for posts without one); `GET /posts?account=&status=&post=` (full page), `GET /posts/table?account=&status=` (fragment). The table's element id is `posts-table`; the detail pane's id is `detail` (Task 7 fills it). A `_Row` has `post`, `status`, `planned`, `sent`.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_posts.py`:
```python
from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")

from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.domain.account import Account  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import post  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402

OLD, NEW, DRAFT = "20260913-0001", "20260914-0002", "20260915-0003"


def _posts(ctx):
    """NEW (rendered, @reads), OLD (not rendered, no account), DRAFT (no picks, @reads)."""
    ctx.store.accounts.add(Account(handle="reads", sounds=["Dark Aria"]))
    posts = ctx.tools.posts
    posts.save(post(id=OLD, created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    posts.save(post(id=NEW, account="reads", created_at=datetime(2026, 9, 14, tzinfo=timezone.utc)))
    posts.save(post(id=DRAFT, account="reads", items=[],
                    created_at=datetime(2026, 9, 15, tzinfo=timezone.utc)))
    render_post(NEW, ctx.tools)
    return ctx


def _order(html: str) -> list[str]:
    return sorted((OLD, NEW, DRAFT), key=lambda pid: html.find(pid) if pid in html else 10**9)


def test_the_page_lists_posts_newest_first_with_their_status(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        html = client.get("/posts").text
    assert "<html" in html and 'id="posts-table"' in html and 'id="detail"' in html
    assert _order(html) == [DRAFT, NEW, OLD]
    for status in ("draft", "rendered", "not rendered"):
        assert f'<span class="status">{status}</span>' in html


def test_filters_by_account_and_status(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        reads = client.get("/posts/table", params={"account": "reads"}).text
        none = client.get("/posts/table", params={"account": "none"}).text
        rendered = client.get("/posts/table", params={"status": "rendered"}).text
    assert NEW in reads and DRAFT in reads and OLD not in reads
    assert OLD in none and NEW not in none
    assert NEW in rendered and OLD not in rendered and DRAFT not in rendered
    assert "<html" not in reads  # a fragment


def test_no_posts_says_so(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        assert "No posts yet" in client.get("/posts").text


def test_a_selected_post_loads_into_the_detail_pane(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        html = client.get("/posts", params={"post": NEW}).text
    assert f'hx-get="/posts/{NEW}"' in html
```
(`post(items=[])` must produce a post whose `is_unfinished` is true; check `tests/unit/fakes.py:post` — if it rejects `items=[]`, build the draft with `post(...).model_copy(update={"items": []})` before saving.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_posts.py -v`
Expected: FAIL — 404 on `/posts`.

- [ ] **Step 3: Write the route and templates**

`src/manhwatok/web/routes/posts.py`:
```python
"""Posts: every post with its status, filters, and (in the detail pane) its slides."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from manhwatok.app.context import AppContext
from manhwatok.app.post_view import post_status, scheduled_text, sent_text
from manhwatok.domain.account import DEFAULT_TIMEZONE
from manhwatok.domain.post import ListPost
from manhwatok.web.routes.common import ctx_of, page

router = APIRouter()

STATUSES = ("draft", "not rendered", "rendered", "exported", "sent")
NO_ACCOUNT = "none"  # the account filter's value for posts built without one


@dataclass
class _Row:
    post: ListPost
    status: str
    planned: str  # in the post's account's time zone
    sent: str


def _rows(ctx: AppContext, account: str, status: str) -> list[_Row]:
    zones = {a.handle: a.timezone for a in ctx.store.accounts.list()}
    wanted = account.strip().lstrip("@")
    rows = []
    for post in sorted(ctx.tools.posts.list(), key=lambda p: p.created_at, reverse=True):
        if wanted and (post.account or NO_ACCOUNT) != wanted:
            continue
        state = post_status(post, ctx.tools.posts)
        if status and state != status:
            continue
        zone = zones.get(post.account or "", DEFAULT_TIMEZONE)
        rows.append(_Row(post, state, scheduled_text(post, zone), sent_text(post, zone)))
    return rows


@router.get("/posts", response_class=HTMLResponse)
def posts_page(
    request: Request, account: str = "", status: str = "", post: str = ""
) -> HTMLResponse:
    ctx = ctx_of(request)
    return page(
        request,
        "posts.html",
        page="posts",
        rows=_rows(ctx, account, status),
        accounts=ctx.store.accounts.list(),
        statuses=STATUSES,
        no_account=NO_ACCOUNT,
        account=account,
        status=status,
        selected=post,
    )


@router.get("/posts/table", response_class=HTMLResponse)
def posts_table(request: Request, account: str = "", status: str = "") -> HTMLResponse:
    return page(
        request, "_posts_table.html", rows=_rows(ctx_of(request), account, status), selected=""
    )
```

`src/manhwatok/web/templates/posts.html`:
```html
{% extends "base.html" %}
{% block title %}Posts · manhwatok{% endblock %}
{% block content %}
<div class="posts">
  <section>
    <form id="filters" class="filters" hx-get="/posts/table" hx-target="#posts-table" hx-trigger="change">
      <select name="account" aria-label="Account">
        <option value="">every account</option>
        {% for a in accounts %}
        <option value="{{ a.handle }}" {% if a.handle == account %}selected{% endif %}>{{ a.display }}</option>
        {% endfor %}
        <option value="{{ no_account }}" {% if account == no_account %}selected{% endif %}>no account</option>
      </select>
      <select name="status" aria-label="Status">
        <option value="">any status</option>
        {% for s in statuses %}
        <option value="{{ s }}" {% if s == status %}selected{% endif %}>{{ s }}</option>
        {% endfor %}
      </select>
    </form>
    <div id="posts-table" hx-get="/posts/table" hx-include="#filters"
         hx-trigger="changed-posts from:body, changed-store from:body">
      {% include "_posts_table.html" %}
    </div>
  </section>
  <section id="detail" class="detail">
    {% if selected %}
    <div hx-get="/posts/{{ selected }}" hx-trigger="load" hx-swap="outerHTML"></div>
    {% else %}
    <p class="muted">Pick a post to see its slides.</p>
    {% endif %}
  </section>
</div>
{% endblock %}
```

`src/manhwatok/web/templates/_posts_table.html`:
```html
{% if rows %}
<form id="bulk">
<table>
  <thead><tr><th></th><th>Post</th><th>Account</th><th>Title</th><th>Status</th><th>Planned</th><th>Sent</th></tr></thead>
  <tbody>
  {% for row in rows %}
  <tr {% if row.post.id == selected %}class="selected"{% endif %}>
    <td><input type="checkbox" name="ids" value="{{ row.post.id }}" aria-label="Select {{ row.post.id }}"></td>
    <td class="link" hx-get="/posts/{{ row.post.id }}" hx-target="#detail" hx-swap="innerHTML"
        hx-push-url="/posts?post={{ row.post.id }}">{{ row.post.id }}</td>
    <td>{{ "@" ~ row.post.account if row.post.account else "-" }}</td>
    <td>{{ row.post.title or "(untitled)" }}</td>
    <td><span class="status">{{ row.status }}</span></td>
    <td>{{ row.planned }}</td>
    <td>{{ row.sent }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
</form>
{% else %}
<p class="muted">No posts yet — build one with <code>manhwatok build</code> or the TUI.</p>
{% endif %}
```
`Account.display` exists (the CLI prints it: `@handle`). Post titles may hold `*accent*` markers; showing them raw is fine for step 1 (the TUI uses `plain_title`; use `{{ row.post.title | replace("*", "") }}` if you prefer the TUI's look).

In `server.py`: `from manhwatok.web.routes import header, posts` and `app.include_router(posts.router)`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/web -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/manhwatok/web tests/web/test_posts.py
git commit -m "feat(web): the Posts page — every post with its status and filters"
```

---

### Task 7: The post detail pane and the files route

**Files:**
- Create: `src/manhwatok/web/routes/files.py`
- Create: `src/manhwatok/web/templates/_post_detail.html`, `_post_gone.html`
- Modify: `src/manhwatok/web/routes/posts.py` (detail route), `src/manhwatok/web/server.py` (include `files.router`)
- Test: `tests/web/test_files.py`, more tests in `tests/web/test_posts.py`

**Interfaces:**
- Consumes: `rendered_files`, `cover_version` (`manhwatok.app.render_post`), `caption_text` (Task 1), `upload_title`, `upload_description` (`manhwatok.domain.caption`), `sounds_for`, `visibility_for` (`manhwatok.app.upload_post`), `AccountNotFound`, `PostNotFound`, `ManhwatokError` (`manhwatok.domain.errors`), `CoverStyle`, `Visibility` (`manhwatok.domain.models`).
- Produces: `GET /posts/{post_id}` (fragment: `_post_detail.html`, or `_post_gone.html` when the post isn't there); `GET /files/{post_id}/{name}` (a PNG/JPEG/WebP inside that post's folder, else 404); `file_url(path: Path) -> str` in `routes/files.py` (`/files/<post>/<name>?v=<mtime_ns>`). The detail's outer element is `<div id="post-detail" data-post="{id}" hx-get="/posts/{id}" hx-trigger="changed-posts from:body, changed-store from:body" hx-swap="outerHTML">` so it refreshes itself; Task 8 adds its buttons inside `<div class="actions">`.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_files.py`:
```python
import os

import pytest

pytest.importorskip("fastapi")

from manhwatok.app.render_post import render_post  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import post  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402

PID = "20260914-0002"


def _rendered(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.tools.posts.save(post(id=PID))
    render_post(PID, ctx.tools)
    return ctx


def test_a_slide_is_served(tmp_path):
    with client_for(_rendered(tmp_path)) as client:
        response = client.get(f"/files/{PID}/01.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


@pytest.mark.parametrize(
    "url",
    [
        f"/files/{PID}/caption.txt",  # not a picture
        f"/files/{PID}/99.png",  # not there
        "/files/20260101-0000/01.png",  # no such post
        f"/files/{PID}/..%2Fpost.json",
        "/files/..%2F..%2Fetc/passwd.png",
        f"/files/{PID}/.hidden.png",
    ],
)
def test_nothing_else_is_served(tmp_path, url):
    with client_for(_rendered(tmp_path)) as client:
        assert client.get(url).status_code == 404


def test_a_link_inside_a_post_folder_is_not_followed(tmp_path):
    ctx = _rendered(tmp_path)
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"\x89PNG secret")
    os.symlink(outside, ctx.tools.posts.folder(PID) / "link.png")
    with client_for(ctx) as client:
        assert client.get(f"/files/{PID}/link.png").status_code == 404
```

Append to `tests/web/test_posts.py`:
```python
def test_the_detail_shows_slides_covers_caption_and_what_tiktok_gets(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        html = client.get(f"/posts/{NEW}").text
    assert 'id="post-detail"' in html and "<html" not in html
    assert html.count("data-slide") == 5  # one per rendered slide
    assert f'src="/files/{NEW}/01.png?v=' in html
    for style in ("fan", "quad", "hero"):
        assert f"/files/{NEW}/cover-{style}.png" in html
    assert 'class="chosen"' in html  # the post's own cover (fan)
    assert "Dark Aria" in html  # the account's sound
    assert "everyone (the account's)" in html


def test_a_post_without_its_account_still_shows(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    ctx.store.accounts.remove("reads")
    with client_for(ctx) as client:
        response = client.get(f"/posts/{NEW}")
    assert response.status_code == 200
    assert "@reads (removed)" in response.text


def test_a_draft_says_it_has_no_picks(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        html = client.get(f"/posts/{DRAFT}").text
    assert "no picks yet" in html and "data-slide" not in html


def test_a_post_deleted_elsewhere_says_it_is_gone(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        from manhwatok.app.delete_post import delete_post

        delete_post(NEW, ctx.tools.posts)
        response = client.get(f"/posts/{NEW}")
    assert response.status_code == 200
    assert f"Post {NEW} is gone" in response.text
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_files.py tests/web/test_posts.py -v`
Expected: the new tests FAIL (404s).

- [ ] **Step 3: Write the files route**

`src/manhwatok/web/routes/files.py`:
```python
"""A post's pictures (slides, cover versions, art) for the page. Only plain picture names
straight inside a post's own folder, never a link: nothing else on the disk is reachable."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from manhwatok.web.routes.common import ctx_of

router = APIRouter()

POST_ID = re.compile(r"^[0-9A-Za-z_-]+$")
PICTURE = re.compile(r"^[0-9A-Za-z_-][0-9A-Za-z_.-]*\.(png|jpe?g|webp)$")


def file_url(path: Path) -> str:
    """The URL of a picture in a post's folder; its mtime in the URL lets the browser keep it
    until a render redraws it."""
    return f"/files/{path.parent.name}/{path.name}?v={path.stat().st_mtime_ns}"


@router.get("/files/{post_id}/{name}")
def post_file(request: Request, post_id: str, name: str) -> FileResponse:
    if not POST_ID.match(post_id) or not PICTURE.match(name) or ".." in name:
        raise HTTPException(404)
    folder = ctx_of(request).tools.posts.folder(post_id)
    path = folder / name
    if folder.is_symlink() or path.is_symlink() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})
```
In `server.py`: include `files.router`.

- [ ] **Step 4: Write the detail route and templates**

Add to `src/manhwatok/web/routes/posts.py`:
```python
from pathlib import Path

from manhwatok.app.post_view import caption_text
from manhwatok.app.render_post import cover_version, rendered_files
from manhwatok.app.upload_post import sounds_for, visibility_for
from manhwatok.domain.account import Account
from manhwatok.domain.caption import upload_description, upload_title
from manhwatok.domain.errors import AccountNotFound, ManhwatokError, NotRendered, PostNotFound
from manhwatok.domain.models import CoverStyle, Visibility
from manhwatok.web.routes.files import file_url


@dataclass
class _Cover:
    style: str
    url: str | None  # None until a render draws it
    chosen: bool


@dataclass
class _Detail:
    post: ListPost
    status: str
    account: Account | None
    account_label: str
    slides: list[str]
    covers: list[_Cover]
    caption: str
    rendered: bool
    title: str
    description: str
    sounds: list[str]
    visibility: str
    planned: str
    sent: str


def _account(ctx: AppContext, post: ListPost) -> tuple[Account | None, str]:
    if not post.account:
        return None, "no account"
    try:
        return ctx.store.accounts.get(post.account), f"@{post.account}"
    except AccountNotFound:
        return None, f"@{post.account} (removed)"


def _detail(ctx: AppContext, post_id: str) -> _Detail:
    posts = ctx.tools.posts
    post = posts.get(post_id)
    account, label = _account(ctx, post)
    try:
        slides = [file_url(p) for p in rendered_files(post, posts)[0]]
    except NotRendered:
        slides = []
    covers = []
    for style in CoverStyle:
        path: Path = cover_version(post.id, style, ctx.tools)
        covers.append(_Cover(style.value, file_url(path) if path.is_file() else None,
                             style is post.cover))
    caption, rendered = caption_text(post, posts)
    if account is not None:
        shown = visibility_for(post, account)
        sounds = sounds_for(post, account, ctx.store.themes)
    else:
        shown, sounds = post.visibility or Visibility.EVERYONE, []
    visibility = shown.spoken + ("" if post.visibility else " (the account's)")
    zone = account.timezone if account else DEFAULT_TIMEZONE
    unfinished = post.is_unfinished
    return _Detail(
        post=post,
        status=post_status(post, posts),
        account=account,
        account_label=label,
        slides=slides,
        covers=covers,
        caption=caption,
        rendered=rendered,
        title="" if unfinished else upload_title(post),
        description="" if unfinished else upload_description(post),
        sounds=sounds,
        visibility=visibility,
        planned=scheduled_text(post, zone),
        sent=sent_text(post, zone),
    )


@router.get("/posts/{post_id}", response_class=HTMLResponse)
def post_detail(request: Request, post_id: str) -> HTMLResponse:
    try:
        detail = _detail(ctx_of(request), post_id)
    except PostNotFound:
        return page(request, "_post_gone.html", post_id=post_id, why="")
    except ManhwatokError as e:  # e.g. an unreadable post.json
        return page(request, "_post_gone.html", post_id=post_id, why=str(e))
    return page(request, "_post_detail.html", d=detail, visibilities=list(Visibility))
```
Route order matters: `/posts/table` must be declared **before** `/posts/{post_id}` in the file (it is, since this is appended after it).

`src/manhwatok/web/templates/_post_detail.html`:
```html
<div id="post-detail" data-post="{{ d.post.id }}" hx-get="/posts/{{ d.post.id }}"
     hx-trigger="changed-posts from:body, changed-store from:body" hx-swap="outerHTML">
  <h2>{{ d.post.title or "(untitled)" }}</h2>
  <p class="muted">{{ d.post.id }} · {{ d.account_label }} · <span class="status">{{ d.status }}</span>
    · planned {{ d.planned }} · sent {{ d.sent }} · visible to {{ d.visibility }}</p>

  <div class="actions"></div>

  {% if d.post.is_unfinished %}
  <p class="muted">no picks yet — pick titles for it (Edit picks comes with the Build page).</p>
  {% else %}
    {% if d.slides %}
    <div class="slides" data-gallery>
      {% for url in d.slides %}<img src="{{ url }}" data-slide alt="slide {{ loop.index }}" loading="lazy">{% endfor %}
    </div>
    {% else %}
    <p class="muted">Not rendered yet.</p>
    {% endif %}

    <h3>Cover</h3>
    <div class="covers">
      {% for c in d.covers %}
      <figure {% if c.chosen %}class="chosen"{% endif %}>
        {% if c.url %}<img src="{{ c.url }}" alt="{{ c.style }} cover">{% else %}<div class="muted">not drawn yet</div>{% endif %}
        <figcaption>{{ c.style }}</figcaption>
      </figure>
      {% endfor %}
    </div>

    <h3>On TikTok</h3>
    <p><strong>Title</strong> {{ d.title }}</p>
    <div class="caption">{{ d.description }}</div>
    <p><strong>Sounds</strong> {{ d.sounds | join(" | ") if d.sounds else "–" }}</p>

    <h3>{{ "Caption" if d.rendered else "Caption (not rendered)" }}</h3>
    <div class="caption">{{ d.caption }}</div>
  {% endif %}
</div>
```

`src/manhwatok/web/templates/_post_gone.html`:
```html
<div id="post-detail">
  <p>Post {{ post_id }} is gone{% if why %} — {{ why }}{% endif %}.</p>
</div>
```
`post.is_unfinished` and `post.title` are plain attributes, so Jinja reads them directly.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/web -v`
Expected: all PASS. If `delete_post` in the gone test needs `chapters`, pass `ctx.store.chapters`.

- [ ] **Step 6: Commit**

```bash
git add src/manhwatok/web tests/web/test_files.py tests/web/test_posts.py
git commit -m "feat(web): a post's slides, covers and captions, and a guarded files route"
```

---

### Task 8: Post actions — render, cover, visibility, export, delete, bulk

**Files:**
- Modify: `src/manhwatok/web/routes/posts.py` (actions), `src/manhwatok/web/templates/_post_detail.html` (buttons), `src/manhwatok/web/templates/_posts_table.html` (bulk bar)
- Test: more tests in `tests/web/test_posts.py`

**Interfaces:**
- Consumes: `done`, `trigger` (Task 5), `RENDER`, `Busy` (Task 2), `render_post`, `choose_cover` (`manhwatok.app.render_post`), `set_visibility` (`manhwatok.app.upload_post`), `export_post` (`manhwatok.app.export_post`), `delete_post` (`manhwatok.app.delete_post`), `app.state.clock`.
- Produces: `POST /posts/{id}/render`, `POST /posts/{id}/cover` (form `style`), `POST /posts/{id}/visibility` (form `visibility`: `""` = the account's, or a `Visibility` value), `POST /posts/{id}/export`, `POST /posts/{id}/delete`, `POST /posts/bulk` (form `action` in `render`/`export`/`delete`, repeated `ids`). All answer 200 with an `HX-Trigger` notice; renders run in the `render` lane and log `post <id> · <n> slides`; export and delete are refused while a render runs (`still rendering — try again when it's done`, level `warning`), as in the TUI.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_posts.py`:
```python
import json  # noqa: E402

from tests.web.helpers import wait_job  # noqa: E402


def _notice(response) -> dict:
    return json.loads(response.headers["HX-Trigger"])["notice"]


def _last_job(client):
    return client.app.state.jobs.recent()[0]


def test_render_runs_in_the_background_and_reports(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        response = client.post(f"/posts/{OLD}/render")
        assert _notice(response) == {"text": f"rendering post {OLD}…", "level": "info"}
        job = wait_job(client, _last_job(client).id)
    assert job.outcome == f"rendered post {OLD}" and not job.failed
    assert job.log == [f"post {OLD} · 5 slides"]
    assert (ctx.tools.posts.folder(OLD) / "01.png").is_file()


def test_rendering_a_draft_ends_with_its_error(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        client.post(f"/posts/{DRAFT}/render")
        job = wait_job(client, _last_job(client).id)
    assert job.failed and job.outcome.startswith(f"error: post {DRAFT} has no items")


def test_a_second_render_waits_its_turn(tmp_path):
    import threading

    from manhwatok.web.jobs import RENDER

    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        release = threading.Event()
        job = client.app.state.jobs.start(RENDER, "render post a", lambda io: release.wait(5) and "ok")
        busy = client.post(f"/posts/{OLD}/render")
        export = client.post(f"/posts/{NEW}/export")
        release.set()
        wait_job(client, job.id)
    assert _notice(busy)["level"] == "warning"
    assert _notice(export) == {"text": "still rendering — try again when it's done", "level": "warning"}


def test_choosing_a_drawn_cover_swaps_it_in(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    hero = ctx.tools.posts.folder(NEW) / "cover-hero.png"
    with client_for(ctx) as client:
        response = client.post(f"/posts/{NEW}/cover", data={"style": "hero"})
    assert _notice(response) == {"text": f"post {NEW} · hero cover", "level": "info"}
    assert (ctx.tools.posts.folder(NEW) / "01.png").read_bytes() == hero.read_bytes()
    assert ctx.tools.posts.get(NEW).cover.value == "hero"
    assert json.loads(response.headers["HX-Trigger"])["changed-posts"] is True


def test_choosing_a_cover_of_an_unrendered_post_renders_it(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        response = client.post(f"/posts/{OLD}/cover", data={"style": "quad"})
        wait_job(client, _last_job(client).id)
    assert _notice(response)["text"] == f"rendering post {OLD} with the quad cover…"
    assert ctx.tools.posts.get(OLD).cover.value == "quad"


def test_visibility_is_set_and_cleared(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        client.post(f"/posts/{NEW}/visibility", data={"visibility": "private"})
        assert ctx.tools.posts.get(NEW).visibility.value == "private"
        response = client.post(f"/posts/{NEW}/visibility", data={"visibility": ""})
        assert ctx.tools.posts.get(NEW).visibility is None
        bad = client.post(f"/posts/{NEW}/visibility", data={"visibility": "martians"})
    assert _notice(response)["text"] == f"post {NEW} · visible to everyone (the account's)"
    assert _notice(bad)["level"] == "error"


def test_export_copies_the_slides(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        response = client.post(f"/posts/{NEW}/export")
    dest = ctx.settings.export_dir / NEW
    assert _notice(response)["text"] == f"exported → {dest}"
    assert (dest / "01.png").is_file()


def test_delete_removes_the_post(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        response = client.post(f"/posts/{OLD}/delete")
        again = client.post(f"/posts/{OLD}/delete")
    assert not ctx.tools.posts.folder(OLD).exists()
    assert _notice(response) == {"text": f"deleted post {OLD}", "level": "info"}
    assert _notice(again)["level"] == "error"


def test_bulk_render_export_and_delete(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        client.post("/posts/bulk", data={"action": "render", "ids": [OLD, NEW]})
        job = wait_job(client, _last_job(client).id)
        exported = client.post("/posts/bulk", data={"action": "export", "ids": [OLD, NEW]})
        deleted = client.post("/posts/bulk", data={"action": "delete", "ids": [OLD, DRAFT]})
        nothing = client.post("/posts/bulk", data={"action": "delete"})
    assert job.outcome == "rendered 2 posts"
    assert job.log == [f"post {OLD} · 5 slides", f"post {NEW} · 5 slides"]
    assert _notice(exported)["text"] == f"exported 2 posts → {ctx.settings.export_dir}"
    assert _notice(deleted)["text"] == "deleted 2 posts"
    assert not ctx.tools.posts.folder(DRAFT).exists() and ctx.tools.posts.folder(NEW).exists()
    assert _notice(nothing) == {"text": "tick some posts first", "level": "warning"}


def test_a_bulk_action_stops_at_the_first_error_and_says_so(tmp_path):
    ctx = _posts(make_ctx(tmp_path))
    with client_for(ctx) as client:
        response = client.post("/posts/bulk", data={"action": "export", "ids": [NEW, DRAFT, OLD]})
    notice = _notice(response)
    assert notice["level"] == "error"
    assert notice["text"].startswith(f"exported 1 post, then: post {DRAFT} has no items")


def test_the_detail_has_the_buttons(tmp_path):
    with client_for(_posts(make_ctx(tmp_path))) as client:
        html = client.get(f"/posts/{NEW}").text
    for action in ("render", "export", "delete"):
        assert f'hx-post="/posts/{NEW}/{action}"' in html
    assert f'hx-post="/posts/{NEW}/visibility"' in html
    assert f'hx-post="/posts/{NEW}/cover"' in html
    assert "hx-confirm" in html  # delete asks first
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_posts.py -v`
Expected: the new tests FAIL (405/404 on the POST routes).

- [ ] **Step 3: Write the actions**

Add to `src/manhwatok/web/routes/posts.py`:
```python
from dataclasses import replace

from fastapi import Form
from fastapi.responses import Response

from manhwatok.app.delete_post import delete_post
from manhwatok.app.export_post import export_post
from manhwatok.app.render_post import choose_cover, render_post
from manhwatok.app.upload_post import set_visibility
from manhwatok.web.jobs import RENDER, Busy
from manhwatok.web.routes.common import done

STILL_RENDERING = "still rendering — try again when it's done"


def _plural(n: int, word: str = "post") -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _start_render(request: Request, ids: list[str], heading: str, started: str) -> Response:
    """Render `ids` in turn in the render lane; each finished post refreshes the pages."""
    ctx, bus = ctx_of(request), request.app.state.bus

    def work(io) -> str:
        tools = replace(ctx.tools, progress=io.progress)
        for post_id in ids:
            slides = render_post(post_id, tools)
            io.progress(f"post {post_id} · {len(slides)} slides")
            bus.publish("changed", what="posts")
        return f"rendered post {ids[0]}" if len(ids) == 1 else f"rendered {_plural(len(ids))}"

    try:
        request.app.state.jobs.start(RENDER, heading, work)
    except Busy as e:
        return done(request, str(e), "warning")
    return done(request, started)


def _rendering(request: Request) -> bool:
    return request.app.state.jobs.busy(RENDER) is not None


@router.post("/posts/bulk")
def bulk(request: Request, action: str = Form(...), ids: list[str] = Form(default=[])) -> Response:
    if not ids:
        return done(request, "tick some posts first", "warning")
    if action == "render":
        return _start_render(request, ids, f"render {_plural(len(ids))}",
                             f"rendering {_plural(len(ids))}…")
    if action not in ("export", "delete"):
        return done(request, f"no bulk action {action!r}", "error")
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    ctx, finished = ctx_of(request), 0
    verb = "exported" if action == "export" else "deleted"
    try:
        for post_id in ids:
            if action == "export":
                _export(request, post_id)
            else:
                delete_post(post_id, ctx.tools.posts, ctx.store.chapters)
            finished += 1
    except ManhwatokError as e:
        return done(request, f"{verb} {_plural(finished)}, then: {e}", "error", changed=["posts"])
    where = f" → {ctx.settings.export_dir}" if action == "export" else ""
    return done(request, f"{verb} {_plural(finished)}{where}", changed=["posts"])


@router.post("/posts/{post_id}/render")
def render(request: Request, post_id: str) -> Response:
    return _start_render(request, [post_id], f"render post {post_id}",
                         f"rendering post {post_id}…")


@router.post("/posts/{post_id}/cover")
def cover(request: Request, post_id: str, style: str = Form(...)) -> Response:
    ctx = ctx_of(request)
    try:
        chosen = CoverStyle(style)
        choose_cover(post_id, chosen, ctx.tools)
    except NotRendered:
        return _start_render(request, [post_id], f"render post {post_id}",
                             f"rendering post {post_id} with the {style} cover…")
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")
    return done(request, f"post {post_id} · {chosen.value} cover", changed=["posts"])


@router.post("/posts/{post_id}/visibility")
def visibility(request: Request, post_id: str, visibility: str = Form("")) -> Response:
    ctx = ctx_of(request)
    try:
        who = Visibility(visibility) if visibility else None
        set_visibility(ctx.tools.posts, post_id, who)
        detail = _detail(ctx, post_id)
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")
    return done(request, f"post {post_id} · visible to {detail.visibility}", changed=["posts"])


def _export(request: Request, post_id: str) -> Path:
    ctx = ctx_of(request)
    return export_post(
        post_id,
        ctx.tools.posts,
        ctx.store.history,
        ctx.settings.export_dir,
        now=request.app.state.clock(),
        chapters=ctx.store.chapters,
    )


@router.post("/posts/{post_id}/export")
def export(request: Request, post_id: str) -> Response:
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    try:
        dest = _export(request, post_id)
    except ManhwatokError as e:
        return done(request, str(e), "error")
    return done(request, f"exported → {dest}", changed=["posts"])


@router.post("/posts/{post_id}/delete")
def delete(request: Request, post_id: str) -> Response:
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    ctx = ctx_of(request)
    try:
        delete_post(post_id, ctx.tools.posts, ctx.store.chapters)
    except ManhwatokError as e:
        return done(request, str(e), "error")
    return done(request, f"deleted post {post_id}", changed=["posts"])
```
Put the `/posts/bulk` route **before** `/posts/{post_id}/...` routes is not needed (different path shapes), but it must come before any `POST /posts/{post_id}` route with a single segment — there is none. `ManhwatokError`, `NotRendered`, `CoverStyle`, `Visibility`, `Path` are already imported from Task 7.

- [ ] **Step 4: Add the buttons**

In `_post_detail.html`, replace `<div class="actions"></div>` with:
```html
  <div class="actions">
    <button class="primary" hx-post="/posts/{{ d.post.id }}/render" hx-swap="none"
      {% if d.post.sent_at %}hx-confirm="Post {{ d.post.id }} was already sent. Render it again?"{% endif %}>Render</button>
    <button hx-post="/posts/{{ d.post.id }}/export" hx-swap="none">Export</button>
    <form hx-post="/posts/{{ d.post.id }}/visibility" hx-trigger="change" hx-swap="none">
      <select name="visibility" aria-label="Who can see it">
        <option value="" {% if d.post.visibility is none %}selected{% endif %}>the account's</option>
        {% for v in visibilities %}
        <option value="{{ v.value }}" {% if d.post.visibility == v %}selected{% endif %}>{{ v.spoken }}</option>
        {% endfor %}
      </select>
    </form>
    <button class="danger" hx-post="/posts/{{ d.post.id }}/delete" hx-swap="none"
      hx-confirm="Delete post {{ d.post.id }} and its slides?">Delete</button>
  </div>
```
and make each cover figure clickable — replace the `<figure ...>` line with:
```html
      <figure {% if c.chosen %}class="chosen"{% endif %} hx-post="/posts/{{ d.post.id }}/cover"
        hx-vals='{"style": "{{ c.style }}"}' hx-swap="none" title="Use the {{ c.style }} cover">
```
In `_posts_table.html`, right after `<form id="bulk">`:
```html
<div class="actions">
  <button hx-post="/posts/bulk" hx-include="#bulk" hx-vals='{"action": "render"}' hx-swap="none">Render ticked</button>
  <button hx-post="/posts/bulk" hx-include="#bulk" hx-vals='{"action": "export"}' hx-swap="none">Export ticked</button>
  <button class="danger" hx-post="/posts/bulk" hx-include="#bulk" hx-vals='{"action": "delete"}' hx-swap="none"
    hx-confirm="Delete the ticked posts and their slides?">Delete ticked</button>
</div>
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/web -v`
Expected: all PASS. If `delete_post`'s signature in this repo differs (`grep -n "def delete_post" -A2 src/manhwatok/app/delete_post.py`: `delete_post(post_id, posts, chapters=None)`), match it.

- [ ] **Step 6: Commit**

```bash
git add src/manhwatok/web tests/web/test_posts.py
git commit -m "feat(web): render, cover, visibility, export and delete, one post or many"
```

---

### Task 9: Try it for real, document it, full suite

**Files:**
- Modify: `README.md` (new "Web app" section before "## Tests"; add `tests/web` to the Tests section)

- [ ] **Step 1: Run the app against the real data and look at it**

Run (background): `uv run manhwatok web --no-open --port 8421`
Then: `curl -s -H "Host: 127.0.0.1:8421" http://127.0.0.1:8421/posts | head -40` — expect the Posts page HTML with your posts.
Open `http://127.0.0.1:8421/` in a browser and check by hand: the list, a post's slides (click one: lightbox, ← →), the covers, Render (toast when done, slides refresh), a visibility change, an export, the mode switch in the header. Then stop the server with Ctrl-C and check it exits within about 2 seconds with a tab still open.

- [ ] **Step 2: Document it**

Add to `README.md` before `## Tests`:
```markdown
## Web app

```bash
uv sync --extra web          # once
uv run manhwatok web         # opens http://127.0.0.1:8421 in your browser (--port, --no-open)
```

The web app runs on this computer only (127.0.0.1) and does what the TUI does, with the mouse:
so far the **Posts** page — every post with its status, filters by account and status, and for
the selected post its slides full size (click one, then ← →), its cover versions (click one to
use it), what TikTok gets as title and description, its sounds and who can see it. Render,
Export, Delete and visibility work on the post, and Render/Export/Delete on ticked posts too.
The header switches how uploads go (as `b` in the TUI) and shows what is running. Changes made
with the CLI or the TUI show up by themselves. Uploads, Build, Accounts, Themes and the plan
come next.
```
and in `## Tests`, after the `tests/tui` paragraph:
```markdown
`tests/web` drives the web app with FastAPI's test client against the same fakes; it is skipped
unless the web extra is installed.
```

- [ ] **Step 3: Full suite**

Run: `uv run pytest -q -m "not browser"`
Expected: everything PASSES (the previous 1670 plus the new web and post_view tests).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: the web app's Posts page"
```
