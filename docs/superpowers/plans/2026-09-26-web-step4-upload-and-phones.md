# Web app, step 4: upload from the web, phones, and which phone/account — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upload a post from the web app — choosing the upload mode, the phone and the account — and watch it: the live log, the phone's screen, and the questions the upload asks (sound, "Posted?", Story) answered in the page. A Phones page lists the connected phones with a live view of each, and which accounts live on which phone.

**Architecture:** Uploads run `upload_post` (the TUI's and CLI's own flow) in the `browser` lane of step 1's `JobRunner`; its `confirm`/`choose_sound` become the job's questions, shown in a dialog on every open page (SSE `question`/`answered` events, `POST /questions/{id}`). The uploader is built per upload for the chosen mode and phone (`AppContext.uploader_for`). Phones come from `adb devices -l` (`adapters/phones.py`), and a phone's screen is `adb exec-out screencap -p`, fetched on demand by the page about once a second only while it is shown (no background grabbing). Each account gets a `phone` setting (an adb serial): uploads default to it.

**Tech Stack:** as steps 1–3, on branch `feat/web-step1`.

**Spec:** `docs/superpowers/specs/2026-09-26-manhwatok-web-design.md` — build-order step 2 ("Uploads: questions, upload view, phone mirror, bulk upload, Log in"). User decisions on 2026-09-26: the account is the post's own but can be changed at upload (the post then moves to it and is re-rendered, since the byline shows the handle); the phone's screen shows on a Phones page and during uploads; each account remembers its phone.

## Global Constraints

- Everything from steps 1–3 holds (127.0.0.1, guards, notices, 100 columns, tests skip without fastapi, commit trailer).
- The upload never taps Post unless the mode is "phone, posting and sharing to the Story" (`phone-post`), exactly as `upload_post` + `AppiumUploader(auto_post=…)` do today.
- One upload at a time (the `browser` lane); a render can run meanwhile (separate lane) — except that an upload that moves the post to another account renders first inside its own job.
- A phone's screen is only grabbed while a page shows it (no polling when nobody looks), at most one grab per phone at a time, cached ~0.8 s.
- Phone serials are validated (`^[A-Za-z0-9._:-]+$`) before they reach adb.
- Questions: first answer wins; server stop answers no/none (step 1's rule).

## Review Focus

- The account changed at upload to one whose phone isn't connected → the upload says which phone it expected and stops before touching anything (Task 5).
- A question asked while no page is open → it shows up on the next page load, and the job waits (Task 4).
- `adb` missing, or no phone connected → the Phones page says so plainly; uploads in browser mode still work (Tasks 2–3).
- An unauthorized phone (USB debugging prompt not accepted) → listed as "needs you to allow USB debugging on the phone", not usable for uploads (Task 2).
- Two tabs answering the sound question → the first answer is used, the other dialog closes (Task 4).

---

## File Structure

```
src/manhwatok/domain/account.py        MOD  Account.phone
src/manhwatok/app/accounts.py? / cli.py MOD  --phone on account add/set; account show
src/manhwatok/tui/screens/accounts.py   MOD  "phone" field in the form
src/manhwatok/app/move_post.py          NEW  move_post(post_id, handle, accounts, posts) -> ListPost
src/manhwatok/adapters/phones.py        NEW  Phone, list_phones(), screencap()
src/manhwatok/app/context.py            MOD  AppContext.uploader_with + uploader_for(mode, phone)
src/manhwatok/web/server.py             MOD  app.state.phones (Phones helper), routers
src/manhwatok/web/phones.py             NEW  Phones: cached list + per-phone screen cache/lock
src/manhwatok/web/routes/phones.py      NEW  /phones, /phones/{serial}/screen.png, login
src/manhwatok/web/routes/jobs.py        NEW  /jobs/{id}, /jobs/{id}/log, /questions, /questions/{id}
src/manhwatok/web/routes/upload.py      NEW  upload dialog, start, bulk upload
src/manhwatok/web/templates/…           NEW  phones.html, _phone_card.html, job.html, _job_log.html,
                                             _question.html, _upload_dialog.html; MOD base.html,
                                             _post_detail.html, _posts_table.html
src/manhwatok/web/static/app.js / .css  MOD  question dialog, live screens, log autoscroll
tests/unit/test_phones.py, test_move_post.py, test_account_phone.py   NEW
tests/web/test_phones.py, test_jobs_page.py, test_upload.py           NEW
README.md                               MOD
```

---

### Task 1: `Account.phone` and moving a post to another account

**Files:**
- Modify: `src/manhwatok/domain/account.py`, `src/manhwatok/cli.py`, `src/manhwatok/tui/screens/accounts.py`
- Create: `src/manhwatok/app/move_post.py`
- Test: `tests/unit/test_account_phone.py`, `tests/unit/test_move_post.py`

**Interfaces:**
- Produces: `Account.phone: str = ""` (adb serial; blank = any/the only phone); CLI `account add/set --phone SERIAL` (`""` clears), `account show` line `phone`; TUI Accounts form field `phone`.
- Produces: `move_post(post_id: str, handle: str, accounts: AccountRepository, posts: PostRepository) -> ListPost` — sets `post.account` to `handle` (normalized; raises `AccountNotFound` if unknown, `ManhwatokError` for a chapter post: "a chapter post stays on its account"); if the post's byline was the old account's own byline, it becomes the new account's; returns the saved post. Doesn't render.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_account_phone.py`:
```python
from typer.testing import CliRunner

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.cli import app as cli
from manhwatok.domain.account import Account


def test_an_account_remembers_its_phone(tmp_path):
    with SqliteStore(tmp_path / "m.db") as store:
        store.accounts.add(Account(handle="reads", phone="R5CY10GLA9E"))
        assert store.accounts.get("reads").phone == "R5CY10GLA9E"


def test_older_accounts_load_without_one():
    assert Account(handle="reads").phone == ""


def test_the_cli_sets_shows_and_clears_it(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    assert runner.invoke(cli, ["account", "add", "reads"]).exit_code == 0
    assert runner.invoke(cli, ["account", "set", "reads", "--phone", "R5CY10GLA9E"]).exit_code == 0
    shown = runner.invoke(cli, ["account", "show", "reads"]).output
    assert "phone" in shown and "R5CY10GLA9E" in shown
    runner.invoke(cli, ["account", "set", "reads", "--phone", ""])
    assert "R5CY10GLA9E" not in runner.invoke(cli, ["account", "show", "reads"]).output
```

`tests/unit/test_move_post.py`:
```python
import pytest

from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app.move_post import move_post
from manhwatok.domain.account import Account
from manhwatok.domain.errors import AccountNotFound, ManhwatokError
from tests.unit.fakes import chapter_post, make_tools, post


@pytest.fixture
def world(tmp_path):
    tools = make_tools(tmp_path)
    with SqliteStore(tmp_path / "m.db") as store:
        store.accounts.add(Account(handle="old", byline="OLD STUDIO"))
        store.accounts.add(Account(handle="new", byline="NEW STUDIO"))
        store.accounts.add(Account(handle="plain"))
        yield tools, store


def test_moving_changes_the_account_and_its_own_byline(world):
    tools, store = world
    tools.posts.save(post(id="20260926-0001", account="old", byline="OLD STUDIO"))
    moved = move_post("20260926-0001", "@New", store.accounts, tools.posts)
    assert (moved.account, moved.byline) == ("new", "NEW STUDIO")
    assert tools.posts.get("20260926-0001") == moved


def test_a_byline_of_the_posts_own_is_kept(world):
    tools, store = world
    tools.posts.save(post(id="20260926-0001", account="old", byline="Custom"))
    assert move_post("20260926-0001", "plain", store.accounts, tools.posts).byline == "Custom"


def test_an_unknown_account_or_a_chapter_post_is_refused(world):
    tools, store = world
    tools.posts.save(post(id="20260926-0001", account="old"))
    tools.posts.save(chapter_post(id="20260926-0002", account="old"))
    with pytest.raises(AccountNotFound):
        move_post("20260926-0001", "nobody", store.accounts, tools.posts)
    with pytest.raises(ManhwatokError) as e:
        move_post("20260926-0002", "new", store.accounts, tools.posts)
    assert "stays on its account" in str(e.value)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_account_phone.py tests/unit/test_move_post.py -q`
Expected: FAIL (no `phone` field, no `move_post`).

- [ ] **Step 3: Implement**

In `domain/account.py`, after `story_text`:
```python
    # The phone (its adb serial, `adb devices`) this account's TikTok app is logged in on: the
    # phone upload uses it unless told otherwise. Blank: the only phone plugged in.
    phone: str = ""
```
In `cli.py`: a `PHONE = typer.Option(None, "--phone", help='The phone this account is logged in on (its serial, see `adb devices`); the phone upload uses it. "" clears it.')`; add `phone: Optional[str] = PHONE` to `account_add` and `account_set` (after `story_text`), pass it to `_account_fields(..., story_text, phone)`; in `_account_fields` add a `phone: Optional[str] = None` parameter and `"phone": phone` to `scalars`; in `_print_account` add `("phone", a.phone or "-")` after `story text`.
In `tui/screens/accounts.py`: add `"phone"` to `TEXTS` and `"phone": "The phone this account is logged in on — its serial, see `adb devices` (empty = the only one)"` to `LABELS` (last).

`src/manhwatok/app/move_post.py`:
```python
"""Move a post to another account — when it's uploaded as someone else, say. Its byline follows
when it was the old account's own; its other texts stay the post's."""

from __future__ import annotations

from manhwatok.domain.account import normalize_handle
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.post import ListPost
from manhwatok.ports.posts import PostRepository
from manhwatok.ports.store import AccountRepository


def move_post(
    post_id: str, handle: str, accounts: AccountRepository, posts: PostRepository
) -> ListPost:
    post = posts.get(post_id)
    if post.chapter:
        raise ManhwatokError(f"post {post_id} is a chapter post — a chapter post stays on its account")
    new = accounts.get(normalize_handle(handle))
    byline = post.byline
    if post.account:
        try:
            old = accounts.get(post.account)
            if byline == old.byline:
                byline = new.byline
        except ManhwatokError:
            pass  # the old account is gone: the post's own byline stays
    moved = post.model_copy(update={"account": new.handle, "byline": byline})
    posts.save(moved)
    return moved
```
(Keep the long `raise` line under 100 columns by splitting the message string.)

- [ ] **Step 4: Run the tests** — `uv run pytest tests/unit/test_account_phone.py tests/unit/test_move_post.py tests/tui/test_accounts.py -q` → all PASS (the TUI accounts tests must still pass with the new form field; if one counts form fields, update its expected list and rule it).

- [ ] **Step 5: Commit** — `git commit -m "feat: an account remembers its phone; move a post to another account"`

---

### Task 2: Listing phones and grabbing a screen

**Files:**
- Create: `src/manhwatok/adapters/phones.py`
- Test: `tests/unit/test_phones.py`

**Interfaces:**
- Consumes: `_find_adb()` from `adapters/appium_uploader.py` (finds adb on PATH or in the SDK).
- Produces:
  - `Phone` dataclass: `serial: str`, `state: str` (`"device"`, `"unauthorized"`, `"offline"`, …), `model: str` (from `model:` in `adb devices -l`, underscores as spaces; "" if none), property `ready: bool` (`state == "device"`), property `problem: str` (`""` when ready; `"needs you to allow USB debugging on the phone"` for unauthorized; `"is offline — unplug it and plug it back in"` for offline; else `f"is {state}"`).
  - `list_phones(run: Callable[[list[str]], str] | None = None) -> list[Phone]` — runs `adb devices -l`; raises `UploadUnavailable(ADB_HINT)` when adb can't be found.
  - `has_app(serial, package, run=None) -> bool` — `adb -s SERIAL shell pm list packages PACKAGE` contains `package:PACKAGE`.
  - `screencap(serial: str, run_bytes: Callable[[list[str]], bytes] | None = None) -> bytes` — `adb -s SERIAL exec-out screencap -p`; raises `ManhwatokError("could not see the screen of <serial>: …")` on a non-PNG or failed run.
  - `SERIAL = re.compile(r"^[A-Za-z0-9._:-]+$")`; `check_serial(serial) -> str` raises `ManhwatokError("not a phone serial: …")`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_phones.py`:
```python
import pytest

from manhwatok.adapters import phones
from manhwatok.domain.errors import ManhwatokError, UploadUnavailable

DEVICES = """List of devices attached
R5CY10GLA9E            device usb:5-1 product:b6qxeea model:SM_F741B device:b6q transport_id:2
emulator-5554          offline transport_id:3
0123456789ABCDEF       unauthorized usb:1-4 transport_id:4

"""


def test_phones_are_listed_with_their_state_and_model():
    seen = []

    def run(argv):
        seen.append(argv[-2:])
        return DEVICES

    found = phones.list_phones(run)
    assert seen == [["devices", "-l"]]
    assert [(p.serial, p.state, p.model, p.ready) for p in found] == [
        ("R5CY10GLA9E", "device", "SM F741B", True),
        ("emulator-5554", "offline", "", False),
        ("0123456789ABCDEF", "unauthorized", "", False),
    ]
    assert found[2].problem == "needs you to allow USB debugging on the phone"
    assert found[1].problem == "is offline — unplug it and plug it back in"
    assert found[0].problem == ""


def test_no_adb_says_how_to_get_it(monkeypatch):
    monkeypatch.setattr(phones, "_find_adb", lambda: None)
    with pytest.raises(UploadUnavailable) as e:
        phones.list_phones()
    assert "adb" in str(e.value)


def test_whether_tiktok_is_installed():
    def run(argv):
        assert argv[-6:] == ["-s", "R5CY", "shell", "pm", "list", "packages"] or True
        return "package:com.zhiliaoapp.musically\n"

    assert phones.has_app("R5CY", "com.zhiliaoapp.musically", run)
    assert not phones.has_app("R5CY", "com.ss.android.ugc.trill", lambda argv: "")


def test_a_screen_is_a_png():
    png = b"\x89PNG\r\n\x1a\n" + b"rest"
    assert phones.screencap("R5CY", lambda argv: png) == png
    with pytest.raises(ManhwatokError) as e:
        phones.screencap("R5CY", lambda argv: b"error: device offline")
    assert "could not see the screen of R5CY" in str(e.value)


@pytest.mark.parametrize("bad", ["", "a b", "x;rm", "../x", "$(id)"])
def test_serials_are_checked_before_they_reach_adb(bad):
    with pytest.raises(ManhwatokError):
        phones.check_serial(bad)
```

- [ ] **Step 2: Run them to see them fail** — FAIL (no module).

- [ ] **Step 3: Implement**

`src/manhwatok/adapters/phones.py`:
```python
"""The Android phones plugged in over USB, as adb sees them, and a picture of a phone's screen.
Everything goes through `adb`; nothing here drives the phone."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable

from manhwatok.adapters.appium_uploader import ADB_HINT, _find_adb
from manhwatok.domain.errors import ManhwatokError, UploadUnavailable

SERIAL = re.compile(r"^[A-Za-z0-9._:-]+$")
PNG = b"\x89PNG\r\n\x1a\n"

Run = Callable[[list[str]], str]
RunBytes = Callable[[list[str]], bytes]


@dataclass(frozen=True)
class Phone:
    serial: str
    state: str
    model: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "device"

    @property
    def problem(self) -> str:
        if self.ready:
            return ""
        if self.state == "unauthorized":
            return "needs you to allow USB debugging on the phone"
        if self.state == "offline":
            return "is offline — unplug it and plug it back in"
        return f"is {self.state}"


def check_serial(serial: str) -> str:
    if not SERIAL.match(serial or ""):
        raise ManhwatokError(f"not a phone serial: {serial!r}")
    return serial


def _adb() -> str:
    adb = _find_adb()
    if adb is None:
        raise UploadUnavailable(ADB_HINT)
    return adb


def _run(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ManhwatokError(f"adb failed: {e}") from e


def _run_bytes(argv: list[str]) -> bytes:
    try:
        return subprocess.run(argv, capture_output=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ManhwatokError(f"adb failed: {e}") from e


def list_phones(run: Run | None = None) -> list[Phone]:
    """Every phone adb knows of, ready or not."""
    out = (run or _run)([_adb() if run is None else "adb", "devices", "-l"])
    found = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        model = next((p[6:] for p in parts[2:] if p.startswith("model:")), "")
        found.append(Phone(parts[0], parts[1], model.replace("_", " ")))
    return found


def has_app(serial: str, package: str, run: Run | None = None) -> bool:
    argv = [_adb() if run is None else "adb", "-s", check_serial(serial),
            "shell", "pm", "list", "packages", package]
    return f"package:{package}" in (run or _run)(argv).split()


def screencap(serial: str, run_bytes: RunBytes | None = None) -> bytes:
    argv = [_adb() if run_bytes is None else "adb", "-s", check_serial(serial),
            "exec-out", "screencap", "-p"]
    data = (run_bytes or _run_bytes)(argv)
    if not data.startswith(PNG):
        said = data[:120].decode("utf-8", "replace").strip() or "no picture"
        raise ManhwatokError(f"could not see the screen of {serial}: {said}")
    return data
```
Fix the `test_whether_tiktok_is_installed` argv assertion to check the real argv (`["adb", "-s", "R5CY", "shell", "pm", "list", "packages", "com.zhiliaoapp.musically"]`) — drop the `or True`.

- [ ] **Step 4: Run the tests** → PASS. **Step 5: Commit** — `git commit -m "feat: list the phones adb sees and grab a phone's screen"`

---

### Task 3: An uploader per phone and mode; the Phones page

**Files:**
- Modify: `src/manhwatok/app/context.py` (uploader_with, uploader_for), `tests/tui/helpers.py` (make_ctx sets `uploader_with`)
- Create: `src/manhwatok/web/phones.py`, `src/manhwatok/web/routes/phones.py`, `templates/phones.html`, `templates/_phone_card.html`
- Modify: `server.py` (`create_app(..., phones=None)`, `app.state.phones`, router), `templates/base.html` (sidebar "Phones"), `static/app.js` (live screens), `static/app.css`
- Test: `tests/web/test_phones.py`

**Interfaces:**
- Produces (context): `AppContext.uploader_with: Callable[[Settings], Uploader]` (default `container.build_uploader`); `AppContext.uploader_for(mode: str, phone: str = "") -> Uploader` — a copy of `settings` with `uploader`/`auto_post` from `mode` (as `set_upload_mode` maps them) and `phone`, handed to `uploader_with`.
- Produces (web): `web/phones.Phones(list_fn=list_phones, screen_fn=screencap, app_fn=has_app, cache_s=0.8)`: `list() -> list[Phone]` (raises what `list_phones` raises), `screen(serial) -> bytes` (per-serial lock + cache), `tiktok(serial, package) -> bool`. `create_app(ctx, …, phones: Phones | None = None)` → `app.state.phones`.
- Routes: `GET /phones` (page `"phones"`): one `_phone_card.html` per phone — serial, model, problem or "ready", TikTok installed yes/no (ready phones only), the accounts whose `phone` is this serial (and, for the only ready phone, accounts with a blank phone, marked "any phone"), a live screen `<img class="screen" data-live="/phones/{serial}/screen.png">` for ready phones; an error message when adb is missing; "No phone plugged in" when none. `GET /phones/{serial}/screen.png` → PNG (`Cache-Control: no-store`), 404 for a bad serial or a phone that can't be seen.
- JS contract: every `img[data-live]` visible on the page is refreshed about once a second (`src = data-live + "?t=" + Date.now()`), only while the tab is visible; a failed load shows the card's "can't see the screen" text.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_phones.py`:
```python
import pytest

pytest.importorskip("fastapi")

from manhwatok.adapters.phones import Phone  # noqa: E402
from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.errors import ManhwatokError, UploadUnavailable  # noqa: E402
from manhwatok.web.phones import Phones  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\nframe"


def _phones(listed=None, error=None, screens=None):
    grabs = []

    def list_fn():
        if error:
            raise error
        return listed if listed is not None else [
            Phone("R5CY10GLA9E", "device", "SM F741B"), Phone("ABC", "unauthorized")]

    def screen_fn(serial):
        grabs.append(serial)
        if screens is not None and serial not in screens:
            raise ManhwatokError(f"could not see the screen of {serial}: offline")
        return PNG

    phones = Phones(list_fn=list_fn, screen_fn=screen_fn, app_fn=lambda s, p: True, cache_s=60)
    return phones, grabs


def test_the_page_lists_phones_their_state_and_their_accounts(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.store.accounts.add(Account(handle="reads", phone="R5CY10GLA9E"))
    ctx.store.accounts.add(Account(handle="loose"))
    phones, _ = _phones()
    with client_for(ctx, phones=phones) as client:
        html = client.get("/phones").text
    assert '<a href="/phones" aria-current="page"' in html
    assert "SM F741B" in html and "R5CY10GLA9E" in html
    assert 'data-live="/phones/R5CY10GLA9E/screen.png"' in html
    assert "needs you to allow USB debugging on the phone" in html
    assert 'data-live="/phones/ABC/screen.png"' not in html
    assert "@reads" in html and "@loose" in html  # the only ready phone takes the loose ones


def test_no_adb_or_no_phone_says_so(tmp_path):
    phones, _ = _phones(error=UploadUnavailable("phone upload needs adb (Android platform-tools)"))
    with client_for(make_ctx(tmp_path), phones=phones) as client:
        assert "phone upload needs adb" in client.get("/phones").text
    phones, _ = _phones(listed=[])
    with client_for(make_ctx(tmp_path), phones=phones) as client:
        assert "No phone plugged in" in client.get("/phones").text


def test_a_screen_is_served_fresh_and_grabbed_once_per_moment(tmp_path):
    phones, grabs = _phones()
    with client_for(make_ctx(tmp_path), phones=phones) as client:
        first = client.get("/phones/R5CY10GLA9E/screen.png")
        client.get("/phones/R5CY10GLA9E/screen.png")
    assert first.content == PNG and first.headers["content-type"] == "image/png"
    assert first.headers["cache-control"] == "no-store"
    assert grabs == ["R5CY10GLA9E"]  # the second came from the cache


def test_a_bad_serial_or_an_unseen_screen_is_a_404(tmp_path):
    phones, _ = _phones(screens={})
    with client_for(make_ctx(tmp_path), phones=phones) as client:
        assert client.get("/phones/R5CY10GLA9E/screen.png").status_code == 404
        assert client.get("/phones/a%3Bb/screen.png").status_code == 404


def test_an_uploader_is_built_for_the_mode_and_phone(tmp_path):
    ctx = make_ctx(tmp_path)
    built = []
    ctx.uploader_with = lambda settings: built.append(
        (settings.uploader, settings.auto_post, settings.phone)) or "uploader"
    assert ctx.uploader_for("phone-post", "R5CY") == "uploader"
    ctx.uploader_for("browser")
    assert built == [("phone", True, "R5CY"), ("browser", False, "")]
    assert ctx.settings.phone == "" and ctx.settings.uploader == "browser"  # untouched
```

- [ ] **Step 2: Run them to see them fail** — FAIL.

- [ ] **Step 3: Context**

In `app/context.py`: `from dataclasses import dataclass, field, replace`; import `Settings` already there. Add field (after `uploader_factory`):
```python
    # Builds an uploader from settings: per upload, for the mode and phone chosen then.
    uploader_with: Callable[[Settings], Uploader] = field(default=container.build_uploader)
```
and method:
```python
    def uploader_for(self, mode: str, phone: str = "") -> Uploader:
        """An uploader for `mode` ("browser", "phone", "phone-post") on `phone` (a serial, or
        "" for the only one), leaving the app's own settings as they are."""
        if mode not in UPLOAD_MODE_LABELS:
            raise ManhwatokError(f"no upload mode {mode!r}")
        settings = replace(
            self.settings,
            uploader=mode.removesuffix("-post"),
            auto_post=mode.endswith("-post"),
            phone=phone,
        )
        return self.uploader_with(settings)
```
Dataclass field order: a field with a default can't precede non-default fields — `closers` and `_closed` already have defaults, so put `uploader_with` after `uploader_factory` only if all following fields have defaults (they do). In `tests/tui/helpers.py`'s `make_ctx`, pass `uploader_with=lambda settings: browser` so tests never build a real one.

- [ ] **Step 4: The Phones helper and routes**

`src/manhwatok/web/phones.py`:
```python
"""The phones for the web pages: the list, and each phone's screen — grabbed only when a page
asks, one grab per phone at a time, and reused for a moment so several tabs share it."""

from __future__ import annotations

import threading
import time
from typing import Callable

from manhwatok.adapters.phones import Phone, has_app, list_phones, screencap


class Phones:
    def __init__(
        self,
        list_fn: Callable[[], list[Phone]] = list_phones,
        screen_fn: Callable[[str], bytes] = screencap,
        app_fn: Callable[[str, str], bool] = has_app,
        cache_s: float = 0.8,
    ) -> None:
        self._list, self._screen, self._app, self._cache_s = list_fn, screen_fn, app_fn, cache_s
        self._lock = threading.Lock()
        self._grabbing: dict[str, threading.Lock] = {}
        self._frames: dict[str, tuple[float, bytes]] = {}

    def list(self) -> list[Phone]:
        return self._list()

    def tiktok(self, serial: str, package: str) -> bool:
        try:
            return self._app(serial, package)
        except Exception:
            return False

    def screen(self, serial: str) -> bytes:
        with self._lock:
            grabbing = self._grabbing.setdefault(serial, threading.Lock())
        with grabbing:
            at, frame = self._frames.get(serial, (0.0, b""))
            if frame and time.monotonic() - at < self._cache_s:
                return frame
            frame = self._screen(serial)
            self._frames[serial] = (time.monotonic(), frame)
            return frame
```

`src/manhwatok/web/routes/phones.py`:
```python
"""Phones: which are plugged in, what each shows right now, and which accounts live on each."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.adapters.phones import check_serial
from manhwatok.adapters.tiktok_app import TikTokApp
from manhwatok.domain.errors import ManhwatokError
from manhwatok.web.routes.common import ctx_of, page

router = APIRouter()


@router.get("/phones", response_class=HTMLResponse)
def phones_page(request: Request) -> HTMLResponse:
    ctx = ctx_of(request)
    helper = request.app.state.phones
    package = ctx.settings.tiktok_app or TikTokApp().package
    accounts = ctx.store.accounts.list()
    try:
        found, error = helper.list(), ""
    except ManhwatokError as e:
        found, error = [], str(e)
    ready = [p for p in found if p.ready]
    cards = []
    for phone in found:
        here = [a for a in accounts if a.phone == phone.serial]
        loose = [a for a in accounts if not a.phone] if phone.ready and len(ready) == 1 else []
        cards.append({
            "phone": phone,
            "accounts": here,
            "loose": loose,
            "tiktok": helper.tiktok(phone.serial, package) if phone.ready else None,
        })
    return page(request, "phones.html", page="phones", cards=cards, error=error)


@router.get("/phones/{serial}/screen.png")
def phone_screen(request: Request, serial: str) -> Response:
    try:
        frame = request.app.state.phones.screen(check_serial(serial))
    except ManhwatokError:
        raise HTTPException(404) from None
    return Response(frame, media_type="image/png", headers={"Cache-Control": "no-store"})
```
(`check_serial` rejects `a;b` before it reaches adb; the 404 covers both.)

In `server.py`: `create_app(..., phones: "Phones | None" = None)`; `app.state.phones = phones or Phones()`; include `phones.router` (import as `phones as phone_routes` to avoid clashing with the parameter name).

`templates/phones.html`:
```html
{% extends "base.html" %}
{% block title %}Phones · manhwatok{% endblock %}
{% block content %}
<div class="toolbar"><h1>Phones</h1><span class="spacer"></span>
  <a class="button" href="/phones">Look again</a></div>
{% if error %}<p class="empty">{{ error }}</p>
{% elif not cards %}<p class="empty">No phone plugged in. Plug one in with USB debugging on.</p>
{% else %}
<div class="phones">{% for c in cards %}{% include "_phone_card.html" %}{% endfor %}</div>
{% endif %}
{% endblock %}
```

`templates/_phone_card.html`:
```html
<article class="panel phone-card">
  <h2>{{ c.phone.model or "Android phone" }}</h2>
  <p class="muted">{{ c.phone.serial }} ·
    {% if c.phone.ready %}<span class="dot" data-status="sent"></span> ready{% else %}<span class="dot" data-status="not rendered"></span> {{ c.phone.problem }}{% endif %}</p>
  {% if c.phone.ready %}
  <p class="muted">TikTok {{ "installed" if c.tiktok else "not found — install it or set MANHWATOK_TIKTOK_APP" }}</p>
  <div class="screen-frame"><img class="screen" alt="{{ c.phone.model }} screen" data-live="/phones/{{ c.phone.serial }}/screen.png">
    <p class="muted screen-lost" hidden>Can't see the screen right now.</p></div>
  {% endif %}
  <h3>Accounts on it</h3>
  {% if c.accounts or c.loose %}
  <ul class="plain">
    {% for a in c.accounts %}<li>{{ a.display }}</li>{% endfor %}
    {% for a in c.loose %}<li>{{ a.display }} <span class="muted">(any phone)</span></li>{% endfor %}
  </ul>
  {% else %}<p class="muted">None yet — set an account's phone with <code>account set @x --phone {{ c.phone.serial }}</code>.</p>{% endif %}
</article>
```

Sidebar in `base.html`: after the New post link, `<a href="/phones" {% if page == "phones" %}aria-current="page"{% endif %}>Phones</a>`.

CSS (append):
```css
.phones { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 18px; }
.screen-frame { background: #000; border-radius: 22px; padding: 10px; width: fit-content; margin: 10px 0; }
.screen { display: block; height: 520px; aspect-ratio: 9 / 20; object-fit: contain; border-radius: 14px; background: #000; }
ul.plain { list-style: none; padding: 0; margin: 0; }
.job-screen .screen { height: 600px; }
```

JS (append inside the IIFE):
```js
  // Live phone screens: refresh each img[data-live] about once a second while the tab is shown.
  function refreshScreens() {
    if (document.hidden) return;
    document.querySelectorAll("img[data-live]").forEach((img) => {
      if (img.dataset.loading) return;
      img.dataset.loading = "1";
      const next = new Image();
      next.onload = () => { img.src = next.src; delete img.dataset.loading; img.parentElement.querySelector(".screen-lost")?.setAttribute("hidden", ""); };
      next.onerror = () => { delete img.dataset.loading; img.parentElement.querySelector(".screen-lost")?.removeAttribute("hidden"); };
      next.src = img.dataset.live + "?t=" + Date.now();
    });
  }
  setInterval(refreshScreens, 1000);
  refreshScreens();
```

- [ ] **Step 5: Run the tests** — `uv run pytest tests/web tests/tui -q` → all PASS. **Step 6: Commit** — `git commit -m "feat(web): a Phones page with each phone's live screen and its accounts"`

---

### Task 4: Jobs you can watch, and questions answered in the page

**Files:**
- Create: `src/manhwatok/web/routes/jobs.py`, `templates/job.html`, `templates/_job_log.html`, `templates/_question.html`
- Modify: `templates/base.html` (question dialog), `static/app.js`, `static/app.css`, `server.py` (router)
- Test: `tests/web/test_jobs_page.py`

**Interfaces:**
- Consumes: `JobRunner.get/pending/answer/recent`, SSE events `log`, `job`, `question`, `answered` (step 1).
- Produces:
  - `GET /jobs/{id}` (page `"posts"`): heading, `<div id="job-log" hx-get="/jobs/{id}/log" hx-trigger="log from:body, job from:body">` with `_job_log.html` (lines + outcome), and — when the job's `screen` attribute names a phone — `<img class="screen" data-live="/phones/{serial}/screen.png">`. Unknown job → "gone" text.
  - `GET /jobs/{id}/log` → `_job_log.html`.
  - `GET /questions` → `_question.html` with the first pending question (or empty); `POST /questions/{qid}` (form `value`) → answers it (`notice` "answered" / error "that question was already answered").
  - `Job.screen: str | None = None` (new optional field in `jobs.py`) — the phone serial whose screen the job page shows.
  - base.html: `<dialog id="question" hx-get="/questions" hx-trigger="load, question from:body, answered from:body" hx-target="this">` ; app.js opens it (`showModal`) when it has content and closes it when empty.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_jobs_page.py`:
```python
import json
import time

import pytest

pytest.importorskip("fastapi")

from manhwatok.web.jobs import BROWSER  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.web.helpers import client_for, wait_job  # noqa: E402


def _pending(client, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not client.app.state.jobs.pending():
        assert time.monotonic() < deadline
        time.sleep(0.01)
    return client.app.state.jobs.pending()[0]


def test_a_job_page_shows_its_log_and_outcome(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        def work(io):
            io.progress("attached 14 slides")
            return "recorded post x as sent"

        job = client.app.state.jobs.start(BROWSER, "upload post x", work)
        wait_job(client, job.id)
        html = client.get(f"/jobs/{job.id}").text
        log = client.get(f"/jobs/{job.id}/log").text
    assert "upload post x" in html and 'hx-get="/jobs/' in html
    assert "attached 14 slides" in log and "recorded post x as sent" in log


def test_a_phone_jobs_page_shows_the_phone(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        job = client.app.state.jobs.start(BROWSER, "upload", lambda io: "ok")
        job.screen = "R5CY10GLA9E"
        wait_job(client, job.id)
        assert 'data-live="/phones/R5CY10GLA9E/screen.png"' in client.get(f"/jobs/{job.id}").text


def test_a_question_shows_on_any_page_and_the_first_answer_wins(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        job = client.app.state.jobs.start(
            BROWSER, "upload", lambda io: f"sound={io.choose('Sound for @reads', [('Lofi', 'lofi'), ('no sound', '')])}")
        question = _pending(client)
        dialog = client.get("/questions").text
        assert "Sound for @reads" in dialog
        assert f'hx-post="/questions/{question.id}"' in dialog and 'value="lofi"' in dialog
        first = client.post(f"/questions/{question.id}", data={"value": "lofi"})
        second = client.post(f"/questions/{question.id}", data={"value": ""})
        assert wait_job(client, job.id).outcome == "sound=lofi"
        assert client.get("/questions").text.strip() == ""
    assert json.loads(second.headers["HX-Trigger"])["notice"]["level"] == "warning"
    assert first.status_code == 200


def test_an_unknown_job_is_gone(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        assert "gone" in client.get("/jobs/job999").text
```

- [ ] **Step 2: Run them to see them fail** — FAIL.

- [ ] **Step 3: Implement**

In `web/jobs.py`'s `Job` add `screen: str | None = None  # a phone whose screen the job page shows`.

`src/manhwatok/web/routes/jobs.py`:
```python
"""A job's own page (its live log, and the phone it drives), and the questions jobs ask —
shown in a dialog on whatever page is open, answered once."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.domain.errors import ManhwatokError
from manhwatok.web.routes.common import done, page

router = APIRouter()


def _job(request: Request, job_id: str):
    try:
        return request.app.state.jobs.get(job_id)
    except ManhwatokError:
        return None


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str) -> HTMLResponse:
    return page(request, "job.html", page="posts", job=_job(request, job_id), job_id=job_id)


@router.get("/jobs/{job_id}/log", response_class=HTMLResponse)
def job_log(request: Request, job_id: str) -> HTMLResponse:
    return page(request, "_job_log.html", job=_job(request, job_id))


@router.get("/questions", response_class=HTMLResponse)
def question(request: Request) -> HTMLResponse:
    pending = request.app.state.jobs.pending()
    return page(request, "_question.html", q=pending[0] if pending else None)


@router.post("/questions/{question_id}")
def answer(request: Request, question_id: str, value: str = Form("")) -> Response:
    if request.app.state.jobs.answer(question_id, value):
        return done(request, "answered")
    return done(request, "that question was already answered", "warning")
```

`templates/job.html`:
```html
{% extends "base.html" %}
{% block title %}{{ job.heading if job else "Job" }} · manhwatok{% endblock %}
{% block content %}
{% if not job %}<p class="empty">Job {{ job_id }} is gone — only the latest jobs are kept.</p>
{% else %}
<div class="toolbar"><h1>{{ job.heading }}</h1><span class="spacer"></span>
  <a class="button" href="/posts">Back to posts</a></div>
<div class="job">
  <section class="panel"><div id="job-log" hx-get="/jobs/{{ job.id }}/log" hx-trigger="log from:body, job from:body">{% include "_job_log.html" %}</div></section>
  {% if job.screen %}
  <section class="job-screen"><div class="screen-frame">
    <img class="screen" alt="The phone's screen" data-live="/phones/{{ job.screen }}/screen.png">
    <p class="muted screen-lost" hidden>Can't see the phone's screen right now.</p></div></section>
  {% endif %}
</div>
{% endif %}
{% endblock %}
```

`templates/_job_log.html`:
```html
{% if job %}
<ol class="log">{% for line in job.log %}<li>{{ line }}</li>{% endfor %}</ol>
{% if job.running %}<p class="muted">Working…</p>
{% else %}<p class="outcome {{ 'failed' if job.failed else '' }}">{{ job.outcome }}</p>{% endif %}
{% endif %}
```

`templates/_question.html`:
```html
{% if q %}
<form class="question" hx-post="/questions/{{ q.id }}" hx-swap="none">
  <h2>{{ q.text }}</h2>
  <div class="actions">
    {% for label, value in q.choices %}
    <button class="button {{ 'primary' if loop.first else '' }}" name="value" value="{{ value }}">{{ label }}</button>
    {% endfor %}
  </div>
</form>
{% endif %}
```

`base.html`, before `<div id="toasts"`:
```html
  <dialog id="question" hx-get="/questions" hx-trigger="load, question from:body, answered from:body"></dialog>
```

JS (append):
```js
  // A job's question: the dialog opens when it has one, closes when it's answered anywhere.
  const asking = document.getElementById("question");
  document.body.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target !== asking) return;
    const has = asking.innerHTML.trim() !== "";
    if (has && !asking.open) asking.showModal();
    if (!has && asking.open) asking.close();
  });
  asking.addEventListener("cancel", (e) => e.preventDefault());  // answer it; Escape doesn't
  // Keep a job's log scrolled to its latest line.
  document.body.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target.id === "job-log") e.detail.target.scrollTop = e.detail.target.scrollHeight;
  });
```
CSS (append):
```css
.job { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 24px; align-items: start; }
#job-log { max-height: 70vh; overflow: auto; }
.log { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; }
.outcome { font-weight: 700; margin-top: 14px; }
.outcome.failed { color: var(--danger); }
#question { border: 1px solid var(--line); border-radius: 14px; background: var(--panel); color: var(--paper); padding: 22px; min-width: 360px; }
#question::backdrop { background: rgba(12, 11, 16, .7); }
```
Include `jobs.router` in `server.py`.

- [ ] **Step 4: Run the tests** → PASS. **Step 5: Commit** — `git commit -m "feat(web): a job page with its live log and phone, questions answered in the page"`

---

### Task 5: Upload — the dialog, the upload itself, bulk, and log in

**Files:**
- Create: `src/manhwatok/web/routes/upload.py`, `templates/_upload_dialog.html`
- Modify: `templates/_post_detail.html` (Upload button + `#upload-panel`), `templates/_posts_table.html` (Upload ticked), `templates/phones.html` (Log in per account), `server.py`
- Test: `tests/web/test_upload.py`

**Interfaces:**
- Consumes: `upload_post(post_id, posts, accounts, history, uploader, confirm, progress, now, debug, sound=None, choose_sound=None, themes=None, chapters=None, schedule_at=None, ask_sound=False, visibility=None, random_sound=False, pick=at_random) -> bool`, `schedule_for(post, now)`, `visibility_for(post, account, chosen)` (`app/upload_post.py`); `login_account(handle, accounts, uploader, progress) -> Account` (`app/login_account.py`); `move_post` (Task 1); `render_post`; `ctx.uploader_for` (Task 3); `Phones.list` (Task 3); `BROWSER`, `Busy`, `JobIO`.
- Produces:
  - `GET /posts/{id}/upload` → `_upload_dialog.html` into `#upload-panel`: account select (every account; the post's selected), mode select (current `ctx.upload_mode` selected), phone select (ready phones; the account's `phone` selected, else the only ready phone; a note when the account's phone isn't connected), visibility select (blank = as the post/account says), "Keep a debug record" checkbox, the planned time line (`schedule_for`), "Start upload".
  - `POST /posts/{id}/upload` (form `account`, `mode`, `phone`, `visibility`, `debug`) → starts the job in the browser lane, sets `job.screen` for phone modes, answers `HX-Redirect: /jobs/{job.id}`; refusals as notices: busy lane, unknown account, phone mode with a phone that isn't ready (`the phone <serial> isn't ready — it <problem>` / `no phone plugged in`).
  - Inside the job: if the account differs, `move_post` then `render_post` (logged); then `upload_post(..., confirm=io.confirm, choose_sound=lambda sounds: io.choose(f"Sound for @{handle}", [(s, s) for s in sounds] + [("No sound", "")]) or None, schedule_at=schedule_for(post, now), visibility=chosen or None)`; outcome `recorded post <id> as sent` / `nothing recorded`.
  - `POST /posts/bulk` action `upload` → one job uploading the ticked posts in turn, each with its own account and that account's phone, the current mode; refused posts (no account) are logged and skipped.
  - `POST /accounts/{handle}/login` (form `mode`, `phone`) → `login_account` in the browser lane with the uploader for that mode/phone; notice with the login hint; `HX-Redirect` to the job page.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_upload.py`:
```python
import json
import time

import pytest

pytest.importorskip("fastapi")

from manhwatok.adapters.phones import Phone  # noqa: E402
from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.ports.uploader import UploadReport  # noqa: E402
from manhwatok.web.phones import Phones  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import FakeUploader, post  # noqa: E402
from tests.web.helpers import client_for, wait_job  # noqa: E402

PID = "20260914-0002"
PHONE = "R5CY10GLA9E"


def _world(tmp_path, phones=None, report=None):
    uploader = FakeUploader(report)
    ctx = make_ctx(tmp_path, uploader=uploader)
    built = []
    ctx.uploader_with = lambda s: built.append((s.uploader, s.auto_post, s.phone)) or uploader
    ctx.store.accounts.add(Account(handle="reads", phone=PHONE, sounds=["Lofi", "Phonk"]))
    ctx.store.accounts.add(Account(handle="other", byline=""))
    ctx.tools.posts.save(post(id=PID, account="reads"))
    render_post(PID, ctx.tools)
    listed = [Phone(PHONE, "device", "SM F741B")] if phones is None else phones
    helper = Phones(list_fn=lambda: listed, screen_fn=lambda s: b"", app_fn=lambda s, p: True)
    return ctx, uploader, built, helper


def _notice(response):
    return json.loads(response.headers["HX-Trigger"])["notice"]


def _answer_all(client, answers, timeout=5.0):
    """Answer each question as it comes, in order; returns the questions' texts."""
    asked = []
    for value in answers:
        deadline = time.monotonic() + timeout
        while not client.app.state.jobs.pending():
            assert time.monotonic() < deadline, f"no question after {asked}"
            time.sleep(0.01)
        q = client.app.state.jobs.pending()[0]
        asked.append(q.text)
        assert client.app.state.jobs.answer(q.id, value)
    return asked


def test_the_dialog_preselects_the_posts_account_its_phone_and_the_mode(tmp_path):
    ctx, _, _, phones = _world(tmp_path)
    with client_for(ctx, phones=phones) as client:
        html = client.get(f"/posts/{PID}/upload").text
    assert '<option value="reads" selected>' in html and '<option value="other">' in html
    assert f'<option value="{PHONE}" selected>' in html
    assert '<option value="browser" selected>' in html
    assert f'hx-post="/posts/{PID}/upload"' in html


def test_an_upload_asks_its_questions_in_the_page_and_records_the_post(tmp_path):
    ctx, uploader, built, phones = _world(tmp_path)
    with client_for(ctx, phones=phones) as client:
        response = client.post(f"/posts/{PID}/upload", data={
            "account": "reads", "mode": "phone", "phone": PHONE, "visibility": "", "debug": ""})
        job_id = response.headers["HX-Redirect"].rsplit("/", 1)[1]
        asked = _answer_all(client, ["Phonk", "yes"])
        job = wait_job(client, job_id)
    assert asked == ["Sound for @reads", "Posted on @reads?"]
    assert built == [("phone", False, PHONE)]
    assert uploader.uploads[0][4] == "Phonk"
    assert job.outcome == f"recorded post {PID} as sent" and job.screen == PHONE
    assert ctx.tools.posts.get(PID).sent_at is not None


def test_uploading_as_another_account_moves_and_rerenders_the_post_first(tmp_path):
    ctx, uploader, _, phones = _world(tmp_path)
    with client_for(ctx, phones=phones) as client:
        response = client.post(f"/posts/{PID}/upload", data={
            "account": "other", "mode": "browser", "phone": "", "visibility": "private"})
        job_id = response.headers["HX-Redirect"].rsplit("/", 1)[1]
        _answer_all(client, ["no"])
        job = wait_job(client, job_id)
    assert ctx.tools.posts.get(PID).account == "other"
    assert job.log[0] == f"moved post {PID} to @other"
    assert any(line.startswith(f"post {PID} · ") for line in job.log)
    assert uploader.uploads[0][0] == "other" and uploader.uploads[0][7].value == "private"
    assert job.outcome == "nothing recorded"


def test_a_phone_that_isnt_ready_stops_the_upload_before_anything(tmp_path):
    ctx, uploader, built, phones = _world(tmp_path, phones=[Phone(PHONE, "unauthorized")])
    with client_for(ctx, phones=phones) as client:
        response = client.post(f"/posts/{PID}/upload", data={
            "account": "reads", "mode": "phone", "phone": PHONE})
    assert _notice(response) == {
        "text": f"the phone {PHONE} isn't ready — it needs you to allow USB debugging on the phone",
        "level": "error",
    }
    assert built == [] and uploader.uploads == []


def test_no_phone_plugged_in_is_said_for_phone_modes_only(tmp_path):
    ctx, uploader, _, phones = _world(tmp_path, phones=[])
    with client_for(ctx, phones=phones) as client:
        refused = client.post(f"/posts/{PID}/upload", data={"account": "reads", "mode": "phone-post"})
        started = client.post(f"/posts/{PID}/upload", data={"account": "reads", "mode": "browser"})
        _answer_all(client, ["", "no"])
        wait_job(client, started.headers["HX-Redirect"].rsplit("/", 1)[1])
    assert _notice(refused)["text"] == "no phone plugged in — plug one in, or upload in the browser"


def test_an_auto_post_upload_is_recorded_without_asking(tmp_path):
    report = UploadReport(True, True, [], titled=True, posted=True)
    ctx, uploader, built, phones = _world(tmp_path, report=report)
    ctx.store.accounts.update(ctx.store.accounts.get("reads").model_copy(update={"default_sound": "Lofi"}))
    with client_for(ctx, phones=phones) as client:
        response = client.post(f"/posts/{PID}/upload", data={
            "account": "reads", "mode": "phone-post", "phone": PHONE})
        job = wait_job(client, response.headers["HX-Redirect"].rsplit("/", 1)[1])
    assert built == [("phone", True, PHONE)] and client.app.state.jobs.pending() == []
    assert job.outcome == f"recorded post {PID} as sent"


def test_bulk_upload_goes_through_the_ticked_posts_in_turn(tmp_path):
    ctx, uploader, _, phones = _world(tmp_path)
    ctx.store.accounts.update(ctx.store.accounts.get("reads").model_copy(update={"default_sound": "Lofi"}))
    ctx.tools.posts.save(post(id="20260915-0003", account="reads"))
    render_post("20260915-0003", ctx.tools)
    ctx.tools.posts.save(post(id="20260916-0004"))  # no account: skipped
    with client_for(ctx, phones=phones) as client:
        client.post("/posts/bulk", data={"action": "upload", "ids": [PID, "20260915-0003", "20260916-0004"]})
        job = client.app.state.jobs.recent()[0]
        _answer_all(client, ["yes", "no"])
        job = wait_job(client, job.id)
    assert [u[0] for u in uploader.uploads] == ["reads", "reads"]
    assert "post 20260916-0004 has no account — skipped" in job.log
    assert job.outcome == "uploaded 2 posts, recorded 1 as sent"


def test_log_in_runs_on_the_accounts_phone(tmp_path):
    ctx, uploader, built, phones = _world(tmp_path)
    with client_for(ctx, phones=phones) as client:
        response = client.post("/accounts/reads/login", data={"mode": "phone", "phone": PHONE})
        job = wait_job(client, response.headers["HX-Redirect"].rsplit("/", 1)[1])
    assert uploader.logins == ["reads"] and built == [("phone", False, PHONE)]
    assert not job.failed
```

- [ ] **Step 2: Run them to see them fail** — FAIL.

- [ ] **Step 3: The routes**

`src/manhwatok/web/routes/upload.py`:
```python
"""Upload a post from the web app — the same flow as `manhwatok upload` and the TUI's `u`, in
the browser lane: the questions come to the page, and a phone upload shows the phone."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.app.context import UPLOAD_MODE_LABELS
from manhwatok.app.login_account import login_account
from manhwatok.app.move_post import move_post
from manhwatok.app.render_post import render_post
from manhwatok.app.upload_post import schedule_for, upload_post, visibility_for
from manhwatok.domain.account import normalize_handle
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Visibility
from manhwatok.web.jobs import BROWSER, Busy
from manhwatok.web.routes.common import ctx_of, done, page

router = APIRouter()


def _ready_phones(request: Request):
    try:
        return [p for p in request.app.state.phones.list() if p.ready], None
    except ManhwatokError as e:
        return [], str(e)


def _phone_for(request: Request, mode: str, wanted: str) -> str:
    """The serial to upload on (checked), or "" for the browser."""
    if mode == "browser":
        return ""
    try:
        found = request.app.state.phones.list()
    except ManhwatokError as e:
        raise ManhwatokError(str(e)) from e
    ready = [p for p in found if p.ready]
    if wanted:
        match = next((p for p in found if p.serial == wanted), None)
        if match is None:
            raise ManhwatokError(f"the phone {wanted} isn't plugged in")
        if not match.ready:
            raise ManhwatokError(f"the phone {wanted} isn't ready — it {match.problem}")
        return wanted
    if not ready:
        raise ManhwatokError("no phone plugged in — plug one in, or upload in the browser")
    if len(ready) > 1:
        raise ManhwatokError("several phones are plugged in — pick one")
    return ready[0].serial


def _upload_one(ctx, io, post_id: str, handle: str, uploader, now, debug, visibility) -> bool:
    post = ctx.tools.posts.get(post_id)

    def choose_sound(sounds: list[str]) -> str | None:
        choices = [(s, s) for s in sounds] + [("No sound", "")]
        return io.choose(f"Sound for @{handle}", choices) or None

    return upload_post(
        post_id, ctx.tools.posts, ctx.store.accounts, ctx.store.history, uploader,
        io.confirm, io.progress, now=now, debug=debug, choose_sound=choose_sound,
        themes=ctx.store.themes, chapters=ctx.store.chapters,
        schedule_at=schedule_for(post, now), visibility=visibility,
    )


@router.get("/posts/{post_id}/upload", response_class=HTMLResponse)
def upload_dialog(request: Request, post_id: str) -> HTMLResponse:
    ctx = ctx_of(request)
    post = ctx.tools.posts.get(post_id)
    accounts = ctx.store.accounts.list()
    account = next((a for a in accounts if a.handle == post.account), None)
    ready, error = _ready_phones(request)
    phone = account.phone if account and account.phone else (ready[0].serial if len(ready) == 1 else "")
    missing = bool(account and account.phone and account.phone not in {p.serial for p in ready})
    when = schedule_for(post, request.app.state.clock())
    return page(
        request, "_upload_dialog.html", post=post, accounts=accounts, account=account,
        modes=list(UPLOAD_MODE_LABELS.items()), mode=ctx.upload_mode, phones=ready,
        phone=phone, missing=missing, phones_error=error, when=when,
        visibilities=list(Visibility),
        shown=visibility_for(post, account) if account else None,
    )


@router.post("/posts/{post_id}/upload")
def start_upload(
    request: Request,
    post_id: str,
    account: str = Form(""),
    mode: str = Form("browser"),
    phone: str = Form(""),
    visibility: str = Form(""),
    debug: str = Form(""),
) -> Response:
    ctx, bus = ctx_of(request), request.app.state.bus
    try:
        post = ctx.tools.posts.get(post_id)
        handle = normalize_handle(account or post.account or "")
        ctx.store.accounts.get(handle)
        if mode not in UPLOAD_MODE_LABELS:
            raise ManhwatokError(f"no upload mode {mode!r}")
        serial = _phone_for(request, mode, phone)
        chosen = Visibility(visibility) if visibility else None
        uploader = ctx.uploader_for(mode, serial)
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")

    def work(io) -> str:
        if handle != post.account:
            move_post(post_id, handle, ctx.store.accounts, ctx.tools.posts)
            io.progress(f"moved post {post_id} to @{handle}")
            slides = render_post(post_id, replace(ctx.tools, progress=io.progress))
            io.progress(f"post {post_id} · {len(slides)} slides")
        posted = _upload_one(ctx, io, post_id, handle, uploader,
                             request.app.state.clock(), bool(debug), chosen)
        bus.publish("changed", what="posts")
        return f"recorded post {post_id} as sent" if posted else "nothing recorded"

    try:
        job = request.app.state.jobs.start(BROWSER, f"upload post {post_id}", work)
    except Busy as e:
        return done(request, str(e), "warning")
    job.screen = serial or None
    response = done(request, f"uploading post {post_id}…")
    response.headers["HX-Redirect"] = f"/jobs/{job.id}"
    return response


def bulk_upload(request: Request, ids: list[str]) -> Response:
    """The Posts page's "Upload ticked": each post with its own account and that account's
    phone, in the current mode, one after another in one job."""
    ctx, bus = ctx_of(request), request.app.state.bus
    mode = ctx.upload_mode

    def work(io) -> str:
        uploaded = recorded = 0
        for post_id in ids:
            post = ctx.tools.posts.get(post_id)
            if not post.account:
                io.progress(f"post {post_id} has no account — skipped")
                continue
            account = ctx.store.accounts.get(post.account)
            try:
                serial = _phone_for(request, mode, account.phone)
            except ManhwatokError as e:
                io.progress(f"post {post_id}: {e} — skipped")
                continue
            uploader = ctx.uploader_for(mode, serial)
            io.progress(f"— post {post_id} as @{post.account}")
            uploaded += 1
            if _upload_one(ctx, io, post_id, post.account, uploader,
                           request.app.state.clock(), False, None):
                recorded += 1
            bus.publish("changed", what="posts")
        return f"uploaded {uploaded} posts, recorded {recorded} as sent"

    try:
        job = request.app.state.jobs.start(BROWSER, f"upload {len(ids)} posts", work)
    except Busy as e:
        return done(request, str(e), "warning")
    response = done(request, f"uploading {len(ids)} posts…")
    response.headers["HX-Redirect"] = f"/jobs/{job.id}"
    return response


@router.post("/accounts/{handle}/login")
def log_in(request: Request, handle: str, mode: str = Form("browser"), phone: str = Form("")) -> Response:
    ctx = ctx_of(request)
    try:
        account = ctx.store.accounts.get(normalize_handle(handle))
        serial = _phone_for(request, mode, phone or account.phone)
        uploader = ctx.uploader_for(mode, serial)
    except ManhwatokError as e:
        return done(request, str(e), "error")

    def work(io) -> str:
        login_account(account.handle, ctx.store.accounts, uploader, io.progress)
        return f"done — {account.display} can upload now"

    try:
        job = request.app.state.jobs.start(BROWSER, f"log in {account.display}", work)
    except Busy as e:
        return done(request, str(e), "warning")
    job.screen = serial or None
    response = done(request, f"logging in {account.display}…")
    response.headers["HX-Redirect"] = f"/jobs/{job.id}"
    return response
```
In `routes/posts.py`'s `bulk`, before the `render` branch: `if action == "upload": from manhwatok.web.routes.upload import bulk_upload; return bulk_upload(request, ids)` (top-level import is fine if no cycle: `upload.py` doesn't import `posts.py`). Split any line over 100 columns.

Include `upload.router` in `server.py`.

- [ ] **Step 4: The dialog and buttons**

`templates/_upload_dialog.html`:
```html
<form class="panel upload-dialog" hx-post="/posts/{{ post.id }}/upload" hx-swap="none"
      hx-disabled-elt="find button.primary">
  <h3>Upload post {{ post.id }}</h3>
  <div class="edit-grid">
    <label class="field">As
      <select name="account">{% for a in accounts %}<option value="{{ a.handle }}"{% if account and a.handle == account.handle %} selected{% endif %}>{{ a.display }}</option>{% endfor %}</select>
    </label>
    <label class="field">How
      <select name="mode">{% for value, label in modes %}<option value="{{ value }}"{% if value == mode %} selected{% endif %}>{{ label }}</option>{% endfor %}</select>
    </label>
    <label class="field">Phone
      <select name="phone">
        <option value="">{{ "The only one" if phones | length == 1 else "Pick a phone" }}</option>
        {% for p in phones %}<option value="{{ p.serial }}"{% if p.serial == phone %} selected{% endif %}>{{ p.model or p.serial }} ({{ p.serial }})</option>{% endfor %}
      </select>
    </label>
    <label class="field">Who can see it
      <select name="visibility"><option value="">{{ "As set: " ~ shown.spoken if shown else "As set" }}</option>
        {% for v in visibilities %}<option value="{{ v.value }}">{{ v.spoken }}</option>{% endfor %}</select>
    </label>
  </div>
  {% if missing %}<p class="art-error">{{ account.display }}'s phone ({{ account.phone }}) isn't plugged in.</p>{% endif %}
  {% if phones_error %}<p class="muted">{{ phones_error }}</p>{% endif %}
  <p class="muted">{% if when %}Planned for {{ when.astimezone().strftime("%a %d %b %H:%M") }} — the browser upload fills in TikTok's schedule; the phone can't, and says so.{% else %}Goes out now.{% endif %}
    Changing the account moves the post to it and renders it again first.</p>
  <label><input type="checkbox" name="debug"> Keep a debug record if something isn't found</label>
  <div class="actions"><button class="button primary">Start upload</button></div>
</form>
```
The test looks for `'<option value="reads" selected>'` — keep exactly `"{{ a.handle }}"{% if … %} selected{% endif %}>` as written (no space before `{% if`). Same for phone and mode options.

In `_post_detail.html`'s `.actions`, after Export: `<button class="button" hx-get="/posts/{{ d.post.id }}/upload" hx-target="#upload-panel">Upload</button>`, and after the `.actions` div: `<div id="upload-panel"></div>`.
In `_posts_table.html`'s bulk toolbar, after Export ticked: `<button type="button" class="button" hx-post="/posts/bulk" hx-include="#bulk" hx-vals='{"action": "upload"}' hx-swap="none">Upload ticked</button>`.
In `_phone_card.html`, each account `<li>` gets a login button: `<button class="button" hx-post="/accounts/{{ a.handle }}/login" hx-vals='{"mode": "phone", "phone": "{{ c.phone.serial }}"}' hx-swap="none">Log in here</button>` (only for ready phones).

- [ ] **Step 5: Run the tests** — `uv run pytest tests/web -q` → PASS. **Step 6: Commit** — `git commit -m "feat(web): upload a post — choose the account, how, and which phone — and log in"`

---

### Task 6: Try it on the real phone, document it

- [ ] **Step 1:** Start the app on port 8422 **with `uv run`** (so adb/appium/gallery-dl are found as the user's own run finds them). In headless Chrome: the Phones page (the Z Flip6 listed, its live screen changing, its accounts); set `account set animedailyclips --phone R5CY10GLA9E` first — **ask the user before changing their account**, or read the serial into the dialog only. Screenshot.

- [ ] **Step 2: A real upload that posts nothing:** from a throwaway post (New post → save), open Upload, pick mode **phone** (not phone-post), the phone, @animedailyclips; the job page shows the log and the phone's screen; answer the sound question, then **No** to "Posted?". Then discard the TikTok draft on the phone (the cleanup script from the phone round) and delete the throwaway post, and delete the pushed pictures (`content delete … Pictures/manhwatok`). Nothing is posted.

- [ ] **Step 3:** README (Web app): Upload (dialog: account, how, phone, who can see it), the job page (live log, phone screen, questions in a dialog), Phones page, `account set --phone`. Full suite. Commit `docs: uploading and phones in the web app`.
