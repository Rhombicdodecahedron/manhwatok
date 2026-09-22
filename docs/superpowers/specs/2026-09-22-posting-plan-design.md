# Posting plan, queue, and a more automatic manhwatok

## Context
Today every post is hand-driven: fill the Build form (or run `build`), pick art, render, export, then `upload` and answer the sound prompt and "Posted?". Nothing knows *when* a post should go out — no command takes a time, posts have no `scheduled_at`, accounts have no slots (scheduling was left out on purpose in the phase-4 spec). The TUI also can't build chapter posts and only acts on one post at a time.

Goal: each account gets a **posting plan** (slots + a rotation of content), the tool **fills upcoming slots with rendered, ready-to-review posts**, a **Queue tab** shows the week, and `upload` **fills TikTok's own schedule date/time** (the user still clicks the final button — same ToS stance as today, one more field automated).

User decisions: rotation pattern per account · auto build+art+render, then human review · per-account time zone · TikTok schedule field filled by uploader.

Shipped as six phases, each its own commit(s), TDD, suite green at every step. The spec copy goes to `docs/superpowers/specs/2026-09-22-posting-plan-design.md` first.

## Phase A — the next-post engine (+ bug fix)
- **Fix:** `app/upload_post.py` — after the user confirms "Posted?", call `chapters.mark_published` for chapter posts, as `app/export_post.py:41` does. Test in `tests/unit/test_upload_post*.py`.
- **Domain:** `domain/plan.py` — `RotationItem` parsed from strings: `chapter:<title>` (a tracked chapter title) or `theme:<name>`. Pure function `next_item(rotation, cursor) -> (item, new_cursor)`.
- **Account fields** (`domain/account.py`, all defaulted so old rows load): `rotation: list[str] = []`, `rotation_cursor: int = 0`, `timezone: str = "Europe/Paris"` (validated with `zoneinfo`), `art_source: str | None` (default art source for auto-fill, e.g. `pins`).
- **App:** `app/next_post.py::make_next_post(ctx, account) -> ListPost` — reads the next rotation item and:
  - `chapter:` → reuse `build_chapter_post` (`app/chapter_post.py:232`); if the title has no parts left, skip to the next item (and warn).
  - `theme:` → reuse `build_post` with the theme, `prefill_items` (`app/build_post.py:70`) as the picks, then the existing `render --source` art fill (`app/art_options.py`) and `render_post`.
  - Advance the cursor only on success.
- **CLI:** `manhwatok next -a @acct [--count N]` and `account set --rotation ... --timezone ... --art-source ...`.

## Phase B — slots and "fill the week"
- `Account.slots: list[str]` like `"mon 19:00"`, `"daily 12:30"` in the account's time zone. `domain/plan.py::upcoming_slots(account, now, days) -> list[AwareDatetime]`.
- `ListPost.scheduled_at: AwareDatetime | None = None`.
- `app/fill_plan.py::fill(ctx, account, days=7)` — for every upcoming slot with no post whose `scheduled_at` is that slot, call `make_next_post` and stamp `scheduled_at`. Idempotent: running it twice does nothing new. Default horizon is 7 days, capped at 10 (TikTok's scheduling limit).
- CLI: `manhwatok plan show [-a]`, `manhwatok plan fill [-a] [--days 7]`, `manhwatok schedule <post> <when|--clear>`.

## Phase C — Queue tab (TUI)
- New `tui/screens/queue.py`, tab `5` (or the first tab): the next 7 days grouped by day, one row per slot per account — time, account, post title, status (empty / ready / exported / scheduled on TikTok / sent), coloured with the existing status text in `tui/text.py:16`.
- Keys: `f` fill the empty slot (or `F` for all), `enter` open the post in the Posts screen, `m` move to another slot (ChoiceModal), `x` clear the slot, `u` upload with schedule (Phase D).
- Work runs in Textual worker threads, as renders do in `tui/app.py:140-172`.

## Phase D — TikTok schedule field
- `adapters/tiktok_page.py`: selectors for the "Schedule" toggle and the date and time pickers. Captured from the live page into a fixture in `tests/fixtures/` and tested in `tests/browser/`.
- `ports/uploader.py`: the upload request gains an optional `schedule_at`. The Playwright uploader sets it and leaves the final button to the user. It rejects times under 15 minutes or over 10 days ahead with a clear error.
- New `Post.tiktok_scheduled_at` set when the user confirms. The confirmation prompt says "Scheduled?" instead of "Posted?".
- Default sound: `Account.default_sound` or the post's theme's first sound skips the `_choose_sound` prompt (`cli.py:733`); `--ask-sound` brings the prompt back.

## Phase E — chapter build in the TUI
- A Build-tab mode switch, List / Chapter. Chapter mode offers a title (from tracked chapters, `ChapterTable`), language and source, and shows what `chapter next` would build. `Build` runs `build_chapter_post` in a worker and reports progress through the same progress callback.

## Phase F — bulk actions and dates on Posts
- Posts table gains Scheduled and Sent columns (`screens/posts.py:114`).
- `space` marks rows. `r`, `x` and `U` act on all marked rows in a row, and one failure doesn't stop the rest; a summary shows at the end.

## Testing / verification
- Unit: `next_item`, `upcoming_slots` (DST edge in Europe/Paris), fill idempotency, rotation skip on an exhausted chapter, and a mark_published-on-upload regression. Uses the fakes in `tests/unit/fakes.py` and `Clock`.
- TUI: pilot scenarios in `tests/tui/` for the Queue fill, move and clear actions, Chapter build mode, and bulk marks.
- Browser: schedule picker filling against a fixture page.
- End to end by hand: `account set @x --rotation chapter:solo-leveling,theme:isekai --slots "mon 19:00,thu 19:00"`, then `plan fill --days 7`, `plan show`, `manhwatok tui` (Queue tab), then `upload <id>` to check TikTok shows the scheduled time before you click.
- Full `pytest` green after each phase.
