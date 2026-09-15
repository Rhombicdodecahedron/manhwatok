# manhwatok Phase 4: assisted TikTok upload (Playwright)

Parent spec: `2026-09-14-manhwatok-design.md` (Phase 4). Phases 1–3a are merged (accounts, themes, history).

## Goal
Take the manual steps out of posting without automating the final decision: `manhwatok upload <id>` opens a
real, visible Chromium window logged in as the post's account, attaches the slides in order and fills the caption,
then the user reviews and clicks **Post** themselves. The terminal then asks whether it was posted and records it.

## Decisions (made with the user, 2026-09-15)
- Route: **Playwright browser helper**, not the official Content Posting API (which needs a domain + developer app;
  research notes in `~/.cache/claude-scratch/p4-research.md`). The API may be added later behind the same command.
- The user clicks Post. No automatic posting, no schedules, no batch runs.
- Browser: **Playwright's bundled Chromium** (`playwright install chromium`), always visible (headful).
- One persistent browser profile per account; the user logs in by hand once; manhwatok never handles passwords.
- Confirmation: terminal prompt `Posted on @x? [y/N]`; `y` records history + marks the post sent.
- No detection-evasion of any kind: no stealth plugins, fingerprint spoofing, proxy rotation or captcha solving.
  Pacing between steps (not faster than a person) is allowed. Captchas/login checks are completed by the user.
- Known risk, accepted by the user: automating the TikTok website is against TikTok's Terms and may trigger
  captchas or account checks; the page can change and break the helper.

## Commands
```
uv sync --extra upload && uv run playwright install chromium     # one-time

manhwatok login <handle>
manhwatok upload <post-id> [--debug]
manhwatok posts [--account <handle>]          # gains a "sent" marker
manhwatok account remove <handle>             # also offers to delete the saved browser login
```
- `login`: account must exist (`AccountNotFound` otherwise). Opens `<data_dir>/browser/<handle>/` as a persistent
  Chromium profile on `https://www.tiktok.com/login`, prints "Log in to @<handle> in the browser, then close the
  window.", and returns when the window is closed.
- `upload`: post must exist, have an account (else `ManhwatokError("post <id> has no account — build it with
  --account")`), that account must exist, and slides must be up to date (same check as `export`: slide count ==
  `post.slide_count` and `caption.txt` present; else `NotRendered`). Then:
  1. open the account's profile on the upload page (`https://www.tiktok.com/tiktokstudio/upload`);
  2. if the page redirects to login → close, `ManhwatokError("@<h> is not logged in — run: manhwatok login @<h>")`;
  3. attach `01.png … NN.png` in order through the page's file input; wait for the editor to appear;
  4. type the caption (`caption.txt`) into the caption editor at typing speed;
  5. print what worked and any problems (e.g. "caption box not found — paste caption.txt yourself"), plus the
     slides folder path; the window stays open;
  6. prompt `Posted on @<h>? [y/N]`; on `y`: `history.record(account, post_id, ids, now)` and
     `post.sent_at = now` (saved); on `n`/EOF: nothing recorded; then close the browser.
  If the user closes the browser before answering, the prompt still appears (the answer decides).
- `--debug`: when an expected element isn't found, save `screenshot.png` and `page.html` to
  `<data_dir>/debug/<post-id>-<timestamp>/` and print the path.
- `posts`: adds `sent` after the slide-count column for posts with `sent_at`.
- `account remove`: after removing the account row, if `<data_dir>/browser/<handle>/` exists, ask
  `Also delete the saved TikTok login for @<h>? [y/N]` (`--yes` answers yes); history is kept as before.

## Domain / ports
- `ListPost` gains `sent_at: AwareDatetime | None = None` (defaulted; older post.json load unchanged).
- `ports/uploader.py`:
  - `UploadReport(attached: bool, captioned: bool, problems: list[str], debug_dir: Path | None = None)`
  - `Uploader` protocol: `login(handle: str) -> None`; `upload(handle: str, slides: list[Path], caption: str,
    debug: bool) -> UploadReport`; `close() -> None` (closes the browser after the terminal answer).
- New errors (`ManhwatokError`): `UploadUnavailable` (extra/browser missing), `NotLoggedIn`.

## Adapter (`adapters/playwright_uploader.py`, `adapters/tiktok_page.py`)
- `PlaywrightUploader(profiles_dir, debug_dir, page=TikTokPage(), pause=(0.5, 1.5), type_delay_ms=(20, 60))`;
  imports Playwright lazily; missing package or browser → `UploadUnavailable("upload needs: uv sync --extra upload
  && uv run playwright install chromium")`.
- Persistent context: `chromium.launch_persistent_context(profiles_dir / handle, headless=False, viewport=None)`.
  No extra launch args that hide automation.
- `TikTokPage` (plain dataclass of strings/timeouts, the ONLY place with TikTok-specific selectors):
  `login_url`, `upload_url`, `login_url_marker` ("/login"), `file_input` (`input[type=file]`),
  `caption_candidates` (ordered list: a contenteditable in the caption/description area, `[contenteditable=true]`,
  `textarea`), `editor_ready` (a selector that appears once files are accepted), `timeouts` (page 30 s, editor 60 s).
  A test fixture page mirrors this contract.
- Upload steps return problems instead of raising for "element not found" (the user finishes by hand); real
  failures (browser crashed/closed before attach) raise `ManhwatokError`.
- Pacing: random pause in `pause` between steps; caption typed with `type_delay_ms` per character.

## App (`app/upload_post.py`, `app/login_account.py`)
- `upload_post(post_id, posts, accounts, history, uploader, confirm: Callable[[str], bool], progress, now,
  debug) -> bool` (True = recorded as posted).
- `login_account(handle, accounts, uploader)`.
- `container.build_uploader(settings)`; `Settings.browser_dir = data_dir / "browser"`, `Settings.debug_dir = data_dir / "debug"`.

## Testing
- Unit (always): upload_post with a fake uploader — y records history + sent_at; n/EOF records nothing; each
  validation error; problems printed and the prompt still shown; `posts` shows sent; login_account errors;
  account remove offers profile deletion (`--yes`, and declining keeps the folder).
- Browser (skipped unless Playwright + Chromium are installed; marker `browser`): the real adapter against a local
  fixture page (`tests/fixtures/fake_upload.html`: file input accepting multiple images, an element that appears
  after files are set, a contenteditable caption box; a variant without the caption box) served from a temp dir via
  `file://` or a local http server — slides attach in order, caption typed, missing caption → problem not crash,
  `--debug` writes screenshot + html. Temp profiles only; no network.
- Live (manual, once, with the user's real account): `login`, then `upload <id> --debug`; adjust `tiktok_page.py`
  from the debug bundle if TikTok's page differs.

## Out of scope for Phase 4
Automatic posting, scheduling, batch uploads, stealth/captcha tricks, the official Content Posting API, Phase 3b TUI.

## Plan-time adjustments (from prototyping; details in `plans/2026-09-15-phase4-upload.md` → "Deviations from the spec")
- `PlaywrightUploader(headless=False)` flag exists for tests only; `login`/`upload` commands always open a visible window.
- `TikTokPage` timeouts are flat fields (page, editor, caption); elements are searched in all frames, visible ones only.
- `login_account` takes a `progress` callback; exact problem/output messages pinned; uploading an already-sent post warns.
- The debug folder is named after the slides folder (the uploader doesn't receive the post id).
- The `sent` column in `posts` appears only when at least one post is sent.
- Playwright resolved to 1.63.0 (Chromium build 1243). Playwright's sync API can't run inside an asyncio loop —
  the Phase 3b TUI must call the uploader from a worker thread.
- Open questions for the live check: whether TikTok Studio web accepts multi-image photo posts and PNG files,
  and the real caption / editor-ready selectors.
