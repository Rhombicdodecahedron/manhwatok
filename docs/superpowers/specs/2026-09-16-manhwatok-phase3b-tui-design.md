# manhwatok Phase 3b: Textual TUI + song notes

## Superseded: song notes
At merge time on 2026-09-17 (merging `origin/main`), the song note described below was dropped in favour of origin's
`Account.sounds`: each account keeps a list of TikTok sound searches and `upload` asks which one to add, so there is no
per-post song, no `song` command, no `build`/`account --song` and no `s` key. What the TUI shows instead:
- Posts: no song column; the details pane shows the post's account sounds (`Sounds: a | b`, or `Sounds: –`), the
  post's art style (`Art: background`, left out when none) and its emojis when set.
- Upload: before the browser opens, a dialog asks which of the account's sounds to add, plus "no sound" (escape and
  quitting also mean none); `upload_post` gets it through `choose_sound` (`ManhwatokApp.choose_from_thread`).
- Build: no Song field; an Emojis input and an Art select (blank = the account's) are passed to `save_new_post`.
- Accounts: the form edits `sounds` (one line, separated by ` | `), `emojis` and `art`; the table shows `sounds`
  (the sound, or how many) and `art` instead of `song`.
The rest of this spec is unchanged and still describes the song note as it was designed.

Parent spec: `2026-09-14-manhwatok-design.md` (Phase 3, "Textual TUI"). Phases 1–4 are merged (suggest, rendering,
accounts/themes/history, assisted upload). Carry-forward items from the 3a review marked "Phase 3b" are handled here.

## Goal
One terminal app, `manhwatok tui`, that does everything the CLI does — build, edit, render, export, upload, delete
posts; manage accounts and themes — with a live preview of each post: the slides as real images, the caption and the
song to add in TikTok.

## Decisions (made with the user, 2026-09-16)
- Scope: **everything** the CLI does, in one app (posts, build, accounts, themes). `tags`/`suggest` live inside the
  Build screen, not as separate screens.
- Song: a **note only** — a free-text song name or TikTok sound link, per account (default) and per post (override).
  No audio files, no playback, `upload` does not pick the sound, no video rendering. The caption is unchanged.
- Slide preview: **in-terminal images** via `textual-image` (kitty graphics protocol / sixel, half-block fallback on
  other terminals) plus a key that opens the full-size PNG with `xdg-open`.
- Architecture: the TUI calls the existing `app/` use cases in-process (no CLI subprocesses).
- Launch: `manhwatok tui`. `textual` and `textual-image` are an optional extra `tui`
  (`uv sync --extra tui`), like `upload`.

## Screens
```
┌ manhwatok ─ [Posts] Build  Accounts  Themes ───────────────────────┐
│ id        account        title                 status   song       │
│▶a1b2c3   @manhwa.daily  MC *regresses* for…    exported  Die For You│
│ d4e5f6   @manhwa.daily  Villainess…            sent      –          │
├──────────────────────────────┬─────────────────────────────────────┤
│  ┌────────┐                  │ Caption                             │
│  │ slide  │  ◀ 2/7 ▶         │ Manhwa where the MC regresses…      │
│  │ image  │                  │ #manhwa #manhwarec                  │
│  └────────┘                  │ Song: Die For You – The Weeknd      │
│                              │ Picks: 1. SSS-Class Revival Hunter… │
└──────────────────────────────┴─────────────────────────────────────┘
 ←/→ slide  o open  e edit  r render  x export  u upload  d delete
```
Tabs switch with `1`–`4` (and mouse); showing a tab reloads its data and focuses its main widget. `q` quits
(while a dialog is open, `ctrl+q`).

### Posts (home)
- Table: id, account (`-` if none), title (stars stripped), status, song (effective song, `–` if empty), slides.
  Status is `sent` if `sent_at`, else `exported` if `exported_at`, else `draft` if the post is unfinished, else
  `rendered`/`not rendered` by `rendered_files`. Filter by account with `f` (a list dialog: "all accounts" +
  accounts).
  Empty leftover post folders are not listed (same as `posts`).
- Preview pane for the highlighted post:
  - left: the current slide (`01.png …`) in a `textual-image` widget, `◀ n/N ▶`; `←`/`→` flip; `o` runs
    `xdg-open` on the current slide file (error notification if `xdg-open` is missing or fails).
  - right: caption (the `caption.txt` text), song, numbered picks with hooks.
  - When `rendered_files` raises `NotRendered`: "not rendered — press r" instead of the image; caption built from
    the post (`build_caption`) with a "(not rendered)" label. Unfinished post: "no picks — press e".
  - Staleness is only what `rendered_files` checks (slide count + caption present); every TUI save re-renders, so
    CLI-only changes are the only way to see out-of-date slides.
- Actions:
  - `e` edit → Picks screen for this post.
  - `r` render → render worker, then refresh preview.
  - `x` export → `export_post` to the default export dir (`MANHWATOK_EXPORT_DIR` or `~/Downloads/manhwatok`);
    notification with the folder path.
  - `u` upload → Upload screen (below); `U` does the same with `debug=True` (like `upload --debug`).
  - `s` song → one-line input to change this post's song (empty input = use the account's song).
  - `d` delete → confirm modal (`Delete post <id> (<n> slides)?`) → `delete_post`.
  - Any action with no post highlighted → "no post selected".

### Build
1. Query form: account (select; "none" allowed), theme (select; "none") **or** tags/genres inputs, sort, min tag
   rank, how many, allow repeats, chapter counts. Same rule as the CLI: theme or tags/genres, not both (error
   notification). Blank sort/rank/how many = the theme's values or score/60/12; out-of-range numbers are errors.
   A tag search box (`tags` equivalent) lists AniList tags matching a word (the tag list is fetched once per app
   run, then filtered locally; name matches first, at most 30); `enter` adds the tag to the tags input.
2. `Search` → worker runs `suggest_for_account` (progress lines shown under the form).
   No results → "no matches — try fewer tags or a lower min tag rank".
3. Picks screen (below), prefilled with `prefill_items(candidates)`.
4. Post fields: title (filled from the theme unless you typed one), hashtags, accent, song — each blank = account
   default (placeholder shows the default). The accent is checked before searching.
5. `ctrl+s` save → `save_new_post` in the render worker → switch to Posts with the new post highlighted.
Unsaved picks only exist in the Picks screen, whose `esc` asks `Discard your changes?`.

### Picks (shared by Build and edit)
- Two lists: **picks** (ordered, max `MAX_ITEMS`) and **other candidates** (the rest of `post.candidates`).
- `space` moves a title between the lists; `shift+↑`/`shift+↓` reorder picks; `enter` edits the hook (one-line
  input, prefilled); title input at the top (`*stars*` = accent).
- Each row: rank, title, chapter label, hook. Cover thumbnail of the highlighted title in a side pane
  (`CoverCache.cached` only — no downloads just for browsing; blank if not cached).
- `ctrl+s` checks the picks (`check_picks`: title, at least one pick, at most `MAX_ITEMS`, no duplicates) and
  closes with them; while a render runs it says "still rendering" and stays. Edit mode → `update_picks` in the
  render worker → back to Posts. `esc` with changes asks `Discard your changes?`.

### Upload (and login)
A `BrowserScreen(heading, job)` with a progress log, shared by upload and login.
- Runs `upload_post` in the browser worker (see Workers). Progress lines append to the log.
- When `upload_post` asks, a modal `Posted on @x?` with **Yes** / **No** (default No, `esc` = No).
- After the answer the browser is closed and the log ends with `recorded post <id> as sent` / `nothing recorded`,
  then `done — press escape to go back`. `esc` before that says the browser is still open.
- Errors (missing Playwright, not logged in, no account, not rendered) → `error: …` in the log and an error
  notification; the screen stays until `esc`.

### Accounts
- Table: handle, genres, blocked, hashtags, accent (colour swatch), song, repeat days, saved login (yes/no).
- `a` add / `e` or `enter` edit → form with every `account add` field plus song (blank on add = default). Name lists are comma-separated, checked
  through `NameCheck` in a worker; "did you mean …?" and "AniList down, saved anyway" appear as notifications, and
  the form stays open until saving works. Edit sends only changed fields (`update_account`), like `account set`.
- `l` login (no confirm) → `BrowserScreen` running `login_account`; log line "Log in to @x in the browser, then close
  the window.", then "browser closed — once logged in, uploads post as @x".
- `d` remove → confirm modal; if a saved login exists a second modal `Also delete the saved TikTok login?`
  (`forget_login`). History is kept.

### Themes
- Table: name, tags, genres, sort, min tag rank, title.
- `a` add / `e` or `enter` edit / `d` remove (confirm). Edit uses a new `update_theme(themes, names, name,
  changes)` (like `update_account`; only changed tag/genre lists are checked again).
- Same name checks as `theme add`; same form as accounts.

## Song
- `Account.song: str = ""` (stripped). `ListPost.song: str | None = None` — `None` means "use the account's song";
  `""` means "no song for this post".
- `effective_song(post, account) -> str` (pure, `domain/account.py`): `post.song` if not None, else `account.song`
  if there is an account, else `""`. `app/songs.py`: `song_for(post, accounts)` (a removed account → `""`) and
  `set_post_song(post_id, song, posts)`.
- `create_post(..., song: str | None)` stores the override as given (no copying the account default), so a later
  `account set --song` changes posts that never set their own.
- CLI: `build --song TEXT`, `account add/set --song TEXT` (`--song ""` clears), `account show` prints `song:`,
  `posts` gains a song column (effective song, truncated to 24 chars, `-` if empty) shown only when some listed post
  has a song, and `manhwatok song <id> [TEXT]` prints or sets a post's song (`--clear` → back to the account's;
  `TEXT` and `--clear` together is an error).
- Upload: `upload_post` adds the progress line `song: <song>` (when non-empty) before "check the post in the
  browser…", so the CLI and the TUI log both show it.
- No DB migration: accounts are stored as JSON; the new field defaults. Old `post.json` loads unchanged.
- The draft file format does not change.

## Architecture
```
src/manhwatok/app/context.py   AppContext: settings, store, metadata, chapters, PostTools, uploader factory; close()
src/manhwatok/tui/
  __init__.py
  app.py              ManhwatokApp: tabs, the single render worker, the single browser worker, quitting; run()
  text.py             post status / caption / details text (no Textual imports)
  screens/posts.py    list + preview pane + actions
  screens/build.py    query form, tag search
  screens/picks.py    picks editor (build + edit)
  screens/browser.py  progress log for upload and login
  screens/accounts.py
  screens/themes.py
  widgets/slide_preview.py   textual-image wrapper and pager
  widgets/dialogs.py         yes/no, text and choice modals
  widgets/form.py            the account/theme form (saves in a worker)
```
- `cli.py` gets `tui` command: imports `manhwatok.tui.app` lazily; `ImportError` for textual →
  `ManhwatokError("the TUI needs the tui extra — run: uv sync --extra tui")`.

### Prep refactors (app/ and adapters/, before any TUI code)
1. `app/build_post.py`:
   - `prefill_items(candidates) -> list[PostItem]` (first `MAX_ITEMS`, hook = first sentence).
   - `create_post(..., song)`.
   - `save_new_post(candidates, title, items, account, hashtags, accent, song, tools, now) -> tuple[ListPost,
     list[Path]]`: `check_picks`, `create_post` (validates the style), then reserve the id (`new_id`), `_save_new`,
     `render_post` — nothing is written for invalid input. `build_post` (CLI editor path) uses `prefill_items`,
     reserves an id only to save a broken draft, and otherwise calls `save_new_post`.
2. `app/edit_post.py`: `update_picks(post_id, title, items, tools) -> list[Path]` — `check_picks`, only the post's
   candidates, save title/items, clear the saved draft, render. `edit_post` calls it after parsing.
   `set_post_song` (in `app/songs.py`) for the song action (no re-render — the song is not on slides or caption).
3. `app/context.py`: `AppContext` owns the store and the AniList, MangaUpdates and CoverCache HTTP clients (`close()`
   closes all, once); `open_context(settings)` builds it from the `container` builders. The CLI keeps its
   per-command builders; `tui.app.run()` opens one context and closes it after the app exits. Adapters close only
   clients they created; `CachedChapterSource.close()` closes the wrapped source.
4. `SqliteStore` sets `PRAGMA journal_mode=WAL` on open (the store already shares its connection across threads
   with an `RLock` and `check_same_thread=False`).
5. `upload_post`/`login_account` stay as they are; the TUI supplies `confirm`/`progress` callables.

## Workers
- Network work (search, tag search, name checks, cover lookups) runs in `@work(thread=True, exclusive=True,
  group=<screen>)` — a new search cancels the previous one's result (thread keeps running; its result is ignored
  when `worker.is_cancelled`).
- **One render worker for the app** (`group="render"`): cached `FreeTypeFont` objects are shared. Render, edit-save
  and build-save are disabled (binding shows "rendering…") while it runs. Render progress lines go to notifications.
- **Upload/login**: one dedicated worker thread per run, and only one at a time app-wide (a second `u`/`l` →
  "a browser is already open"). Playwright's sync API is bound to its thread, so `upload`, the confirm wait and
  `close()` all happen in that worker:
  - `confirm(question)` = `app.ask_from_thread(question)`: pushes a `ConfirmModal` via `call_from_thread` and waits on
    a `threading.Event` (checking every 0.2 s that the app still runs). `push_screen_wait` can't be used: it only
    works inside async workers.
  - `progress(line)` = `app.call_from_thread(log.write_line, line)`.
  - Quitting while the confirm modal is open → the modal is dismissed with `False` (nothing recorded), the worker
    closes the browser, then the app exits.
  - Quitting while `upload()`/`login()` is still running → "closing the browser…" notification; the app waits for the
    worker to finish (`close()` never raises).
- Everything that touches Textual widgets from a worker goes through `call_from_thread`.

## Errors
- `ManhwatokError` from any action → `app.notify(str(e), severity="error")`; the screen stays as it was.
- Any other exception → Textual's default crash (traceback on exit) — same "bugs are loud" rule as the CLI.
- `DraftError` from `update_picks` can't happen from the TUI's own inputs except zero picks (blocked in the UI).
- `xdg-open` missing → "no image viewer found (xdg-open)".
- Terminal without image support → `textual-image` falls back to half-blocks automatically; no message.

## Testing
- Unit (pytest, TDD): `prefill_items`, `save_new_post`, `update_picks`, `set_post_song`, `effective_song`
  (override, empty override, account default, removed account, no account), old post/account JSON loading without
  `song`, context `close()` idempotent, WAL enabled, CLI `--song` flags, `song` command, `posts` song column,
  `upload_post` song progress line.
- TUI (pytest + `App.run_test()` / `Pilot` inside `asyncio.run`, fakes from `tests/unit/fakes.py`, a real database
  and post folders under `tmp_path`, skipped via `pytest.importorskip("textual")` without the extra; a conftest
  points the data and export dirs at temporary folders):
  - Posts: list shows statuses and effective songs; `→` advances the slide counter; not-rendered post shows the hint;
    `d` + Yes deletes, + No keeps.
  - Build: theme + account → search (fake metadata) → toggle/reorder/edit hook → `ctrl+s` saves a post with those
    picks and renders it (fake renderer); theme and tags together → inline error.
  - Edit: changes picks, saves, re-renders; `esc` with changes asks.
  - Upload: fake uploader; Yes records history + `sent_at`; No records nothing; `close()` called once either way.
  - Accounts/Themes: add, edit (only changed fields), remove (+ forget login prompt when a saved login exists).
  - Errors surface as notifications.
  - The image widget is not stubbed: without a terminal textual-image uses its text fallback, and the test context
    renders real tiny PNGs.
- Live check: `uv run manhwatok tui` in kitty — build a real post from a theme, flip through the slides, open one in
  the image viewer, set a song, export, upload to a test account and answer No.
- No snapshot tests for now.

## Out of scope
- Audio files, playback, sound selection during upload, video output.
- Scheduling, batch uploads.
- `history show/forget` (still open from 3a; can be a later Posts/Accounts action).
- Themes/colours for the TUI beyond Textual defaults.
