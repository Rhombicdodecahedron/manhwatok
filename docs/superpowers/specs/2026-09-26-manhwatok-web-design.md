# manhwatok: local web app

Parent specs: `2026-09-14-manhwatok-design.md`, `2026-09-16-manhwatok-phase3b-tui-design.md` (the TUI this mirrors),
`2026-09-22-posting-plan-design.md` (the plan the calendar shows). The phone upload (Appium, auto-post, Story) is
merged as of `7c8b161`.

## Goal
`manhwatok web`: a web app in the browser of this computer that does everything the TUI does — posts, build, picks,
art, accounts, themes, the plan, uploads and logins — and does four things better than the terminal can:

1. **See slides properly**: full-size slides and cover versions, art options as a real image grid.
2. **Mouse and forms**: ordinary forms, click to pick, drag to reorder and to move posts between slots.
3. **Watch uploads**: the live log of an upload, and a live view of the phone's screen while it posts.
4. **Planning at a glance**: a week calendar of every account's slots and posts.

## Decisions (made with the user, 2026-09-26)
- Reachable from **this computer only**: bound to 127.0.0.1, no login.
- Scope: **everything the TUI does**, in one app.
- Stack: **FastAPI + server-rendered Jinja2 pages + htmx**, live updates over **Server-Sent Events**. No SPA, no
  JavaScript build step. (Rejected: a React/Vite SPA — a second project and toolchain for a local tool; textual-serve —
  it is the terminal UI in a browser tab and gives none of the four points above.)
- Architecture: the web app calls the existing `app/` use cases in-process through an `AppContext`, as the TUI does;
  it never shells out to the CLI. The CLI and TUI are unchanged.
- Launch: `manhwatok web` (opens the browser). `fastapi`, `uvicorn`, `jinja2` and `python-multipart` are an optional
  extra `web` (`uv sync --extra web`), like `tui` and `phone`.

## Layout
A sidebar with the pages below, and a header on every page with:
- the **upload mode** and a switch between browser / phone / phone all by itself (`AppContext.set_upload_mode`,
  as the TUI's `b`), lasting until the server stops;
- the **busy state** of each job lane ("rendering post 20260926-ab12…", "uploading…"), linking to the job.

Every action is a button or a form; there are no keyboard-only actions. Pages work at a laptop's width; phone widths
are not a goal (the app is not reachable from the phone).

## Pages

### Posts
- A table: id, account, title, status (draft / rendered / scheduled / sent, the TUI's `post_status`), date. Filters by
  account and status; a checkbox per row for **bulk** render, upload and delete.
- Selecting a row opens the **detail panel**:
  - the slides as a full-size strip; a click opens a lightbox that steps through them with ← →;
  - the **cover versions** side by side; a click chooses one (`choose_cover`);
  - the title and description exactly as TikTok gets them (`upload_title`, `upload_description`), the sounds on offer
    (`sounds_for`), who can see it, its planned time and TikTok's, and when it was sent;
  - buttons: Edit picks, Render, Art, Visibility, Schedule, Export, Upload, Delete.
- Delete and a re-render of a sent post ask for confirmation first.

### Picks editor (from Build, and "Edit picks")
- Candidates as **cards**: cover, title, genres, chapters, status. A click picks or unpicks.
- The picked titles as a list: **drag to reorder**, a hook line field on each. The post's limits (`MAX_ITEMS`,
  `check_picks`) are checked as on save in the TUI; errors show next to the list.
- Save saves the post and starts its render in the render lane; the post opens in Posts and its slides appear when
  the render is done.

### Art picker (one title of a post)
- Every option of the chosen source — AniList covers, MangaDex volume covers, fanart, Pinterest, Reddit — as a large
  **image grid**, with the source switch and the sort (relevance / size / portrait / popular, `ArtOrder`).
- A click uses that picture; a URL field and a file upload use one of the user's own; "Clear" drops the title's art.
  What lands in the post's folder is exactly what `manhwatok art` would leave there.
- The TUI art screen's rules carry over (e.g. what a source says when it has nothing, Reddit's missing credentials).

### Build
- **List post**: choose an account, then search by its own filters, a theme, or tags/genres (as the TUI's Build tab
  and `suggest`); the results open the picks editor.
- **Chapter** tab: a title's next chapter part, as `chapter next` / `chapter build` and the TUI's Chapter mode,
  including the chapter source choice.

### Accounts and Themes
- Lists with Add, Edit, Remove (removing an account asks, as the TUI does, whether to delete its saved browser login).
- The account form is grouped: **Filters** (genres, blocked genres/tags, repeat days), **Style** (accent colour picker,
  byline, emojis, end-slide texts, art), **Sounds** (sounds, default, random), **Plan** (time zone, slots, rotation,
  art source), **Publishing** (visibility, story text). Validation is the TUI form's (`check_accent`, slots, time
  zone…), shown next to the field.
- Accounts has **Log in** (see Jobs).

### Plan
- A **week calendar**: one row per account, one column per day, 7 days from today with ← → a week at a time; times
  in each account's own time zone. Data from `plan_rows` and `overdue_rows`, as the Queue tab.
- A cell is a slot: its time and its post — cover thumbnail, title, status badge (planned / uploading / sent) — or
  "+ fill" when empty. Posts past their time sit in a red **Overdue** strip on top; sent posts are greyed.
- **Drag** a post onto another empty slot of the same account to move it (`schedule_post`); a click opens the post in
  Posts; "+ fill" fills that slot; each row has "Fill account" and the page "Fill all" (`fill`, in the render lane —
  cells fill in as posts are built); each post has Upload and Unschedule.

## Jobs, questions and live updates

### Job lanes
`web/jobs.py` holds two lanes, **render** (renders, saves-and-render, plan fills) and **browser** (uploads, logins).
Each runs one job at a time in a thread; starting a job while its lane is busy is refused with a notice, as in the
TUI. A job has an id, a heading, a log (every `progress` line) and an outcome (the final line, or the error of a
`ManhwatokError`). Bulk uploads run one post after another inside one job.

### Questions
`upload_post` and the upload flow ask questions (which sound, "Posted on @x?", "Add it to your Story?"). In the web
app `confirm` and `choose_sound` create a **pending question** on the job and block its thread until it is answered:
- every open tab shows it as a dialog; the first answer wins and closes it everywhere;
- a tab opened later, or reloaded, shows the still-pending question;
- when the server stops, pending questions are answered no / none (the TUI's rule when quitting).
In "phone all by itself" mode the only question left is the sound, and only when the account doesn't settle it.

### Upload view
Upload (from a post, a plan slot, or ticked posts) opens the job panel:
- header: post, account, mode, planned time;
- the live log;
- in phone mode, the **phone mirror** (below);
- the outcome: "recorded post … as sent", "nothing recorded", or the error.
There is no way to stop an upload midway in v1 (as in the TUI): cutting Appium off mid-step can leave TikTok half
filled.

### Log in
A job in the browser lane: with the phone, the uploader's `login_hint` is shown and the job waits until the user
leaves TikTok; with the browser, Chrome opens on this computer as in `manhwatok login`.

### Phone mirror
`web/phone_mirror.py`: while an upload job runs in phone mode, `adb exec-out screencap -p` about once a second (the
adb the uploader finds, `_find_adb`). The latest frame is kept in memory only, served at `/phone.png`, and each new
frame is announced over SSE so the page swaps the image. It runs separately from Appium, so it does not disturb the
upload; it stops when the job ends. A failing adb shows "phone view unavailable" and never fails the upload.

### Live updates
One SSE stream (`/events`) per tab carries: job started / log line / finished, question asked / answered, phone frame,
and **data changed** (posts, accounts, themes, plan). Pages re-fetch the affected fragment with htmx. Changes made
through the web app announce themselves; changes made elsewhere (CLI, TUI) are found by a watcher that looks at the
posts folder's and the database's modification times every few seconds, as the TUI's tabs already do.

## Code structure
```
src/manhwatok/web/
  server.py         FastAPI app, lifespan (AppContext open/close, job lanes stop), `run()` for `manhwatok web`
  jobs.py           lanes, jobs, pending questions, the event bus — no FastAPI imports
  phone_mirror.py   the screencap loop
  events.py         SSE endpoint, change watcher
  routes/           posts.py, picks.py, art.py, build.py, accounts.py, themes.py, plan.py, jobs.py
  templates/        base.html + one template (and its fragments) per page
  static/           htmx.min.js (vendored), app.js (drag, lightbox, dialogs, SSE), app.css (light and dark)
```
- Logic the TUI keeps in its screens today and the web app needs too moves into `app/` so both use it: the post
  status label (`tui/text.post_status`), and the upload wiring (`tui/screens/posts.upload_in_app`: the sound
  question, `schedule_for`, visibility) as a front-end-neutral function taking `confirm` / `choose_sound` callbacks.
  The TUI then calls the moved code; its behaviour does not change.
- Slides, covers and art are served from the post folders through a route that only serves files inside
  `settings.posts_dir` (no path escapes).
- `manhwatok web` is a CLI command (`--port`, default 8421; `--no-open`). Without the `web` extra it says
  `web needs: uv sync --extra web`, as `tui` does.

## Safety
- Bound to 127.0.0.1 only; no option to bind elsewhere in v1.
- Every state-changing request (POST/PUT/DELETE) must carry an `Origin` (or `Referer`) of the app itself and a
  `Host` of `127.0.0.1:<port>` / `localhost:<port>`; anything else gets 403. This stops another website open in the
  same browser from posting to the app (the app can publish to TikTok), and DNS rebinding.
- File uploads (art) are size-limited and must be images; they go through the same code as `manhwatok art`.

## Testing
- `web/jobs.py` on its own, with threads: one job per lane, a refused second job, a question answered from another
  thread, an answer from a second "tab" after the first, server stop answering no, bulk uploads in order.
- Routes with FastAPI's `TestClient` against a context built like `tests/tui/helpers.make_ctx` (real database and post
  folders under `tmp_path`, `FakeUploader`, fake metadata and art sources): one test file per page, covering each
  action and its errors, and the Origin/Host check.
- The phone mirror with a fake adb command (a frame, a failing adb).
- The moved `app/` code keeps the TUI's existing tests passing unchanged.
- Like `tests/tui`, `tests/web` is skipped when the `web` extra isn't installed.

## Not in v1
Stopping an upload midway; access from other devices or any login; editing post files directly; anything the TUI
cannot do today.

## Build order
The implementation plan builds it in steps that each leave a working app:
1. Server, layout, jobs and events, Posts (list, detail, slides, lightbox, covers, render, visibility, export,
   delete) and the header's mode switch.
2. Uploads: questions, upload view, phone mirror, bulk upload, Log in.
3. Build, picks editor, art picker.
4. Accounts and Themes.
5. Plan calendar (drag to move, fill, overdue) and the change watcher.
