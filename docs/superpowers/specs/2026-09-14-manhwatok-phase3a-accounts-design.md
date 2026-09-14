# manhwatok Phase 3a: accounts, themes, repeat history, delete

Parent spec: `2026-09-14-manhwatok-design.md` (Phase 3, first half). Phases 1–2 are merged.
Phase 3b (Textual TUI) gets its own spec and builds on this.

## Goal
Run several TikTok accounts from one tool: each account has its own genre filters, hashtags,
accent and end-slide text; themes are reusable; titles an account already exported aren't
suggested again within its repeat window; posts can be deleted. Slides switch to the Montserrat
"Clean" look.

## Decisions (made with the user, 2026-09-14)
- Scope split: 3a = accounts/themes/history/delete (CLI); 3b = TUI later.
- Per-account settings: hashtags, accent, end-slide texts, default filters. Fonts are NOT per account.
- Style: Montserrat ("Clean") replaces Anton + Inter for every slide; Anton/Inter files are removed.
- Account filters: allow-list of genres (title needs at least one) + block-lists of genres and tags.
- Repeats: per account, N-day window (default 30), overridable with `--allow-repeats`.
- A post's titles count as posted when the post is **exported** (first export date).
- Themes: one shared library usable by every account.
- Storage: SQLite (`manhwatok.db`) with one owner and schema versioning; posts stay folders.

## Commands
```
manhwatok account add <handle> [--genres A,B] [--block-genres X,Y] [--block-tags "T1,T2"]
                      [--hashtags "..."] [--accent "#rrggbb"] [--cta-title "..."] [--cta-follow "..."]
                      [--repeat-days 30]
manhwatok account set <handle> [same options]      # only the given fields change
manhwatok account list | show <handle> | remove <handle>
manhwatok theme add <name> [-t TAG]... [-g GENRE]... --title "..." [--sort score] [--min-tag-rank 60]
manhwatok theme list | show <name> | remove <name>
manhwatok build [--account <handle>] (--theme <name> | -t/-g ...) [-n 12] [--allow-repeats]
                [--title ...] [--hashtags ...] [--accent ...] [--chapters/--no-chapters]
manhwatok posts [--account <handle>]
manhwatok delete <id> [--yes]
```
- Handles: `@name` or `name`; stored lowercase without `@`; must match `^[a-z0-9._]{2,24}$`
  after normalising. Displayed as `@name`.
- Theme names: `^[a-z0-9][a-z0-9-]{0,39}$`.
- `account add` fails if the handle exists; `account set` fails if it doesn't. Defaults on add:
  no allow-list, no block-lists, hashtags `DEFAULT_HASHTAGS`, accent `#43c9e4`,
  cta_title `Which one have you *read?*`, cta_follow `Follow for part 2`, repeat_days 30.
  List options take comma-separated values; `set --genres ""` clears a list.
- `theme add` needs at least one tag or genre and a non-empty title; fails if the name exists.
- `build`: `--theme` and `-t/-g` are mutually exclusive (error if both); one of them is required.
  A theme supplies tags, genres, sort, min_tag_rank and title; `--title` overrides the theme title.
  `--hashtags`/`--accent` override the account's for this post. Without `--account` the behaviour
  is exactly Phase 2's (no filters, no history, default hashtags/accent/CTA).
- `posts` gains an account column (`@handle` or `-`); `--account` filters.
- `delete` prompts `Delete post <id> (<N> slides)? [y/N]` unless `--yes`; removes the post folder;
  history rows of an exported post are kept.
- `account list`: one line per account (`@handle  genres  blocks  repeat Nd`); `show`: all fields.
  `theme list`/`show` likewise.

## Domain
- `domain/account.py`: `Account(handle, genres: list[str] = [], block_genres: list[str] = [],
  block_tags: list[str] = [], hashtags: str = DEFAULT_HASHTAGS, accent: str = DEFAULT_ACCENT,
  cta_title: str = DEFAULT_CTA_TITLE, cta_follow: str = DEFAULT_CTA_FOLLOW, repeat_days: int = 30 (1..3650))`;
  `normalize_handle(raw) -> str` (raises `InvalidName`); accent validated with `is_hex_color`.
- `domain/theme.py`: `Theme(name, tags: list[str] = [], genres: list[str] = [], sort: Sort = SCORE,
  min_tag_rank: int = 60, title: str)`; validation as above; `to_query(limit) -> SearchQuery`.
- `SearchQuery` gains `exclude_genres: list[str] = []`, `exclude_tags: list[str] = []`.
- `ListPost` gains `account: str | None = None`, `exported_at: AwareDatetime | None = None`,
  `cta_title: str = DEFAULT_CTA_TITLE`, `cta_follow: str = DEFAULT_CTA_FOLLOW` (all defaulted so
  Phase 2 `post.json` files load unchanged).
- `DEFAULT_CTA_TITLE = "Which one have you *read?*"`, `DEFAULT_CTA_FOLLOW = "Follow for part 2"` move
  from `adapters/layout.py` (`END_TITLE`/`FOLLOW`) to `domain/post.py`; `layout_end(names, cta_title,
  cta_follow)` takes them as parameters.
- New errors (`ManhwatokError`): `AccountNotFound`, `ThemeNotFound`, `InvalidName` (bad handle/theme
  name/genre/tag/accent), `AlreadyExists`.

## Store (`adapters/sqlite_store.py`)
- `SqliteStore(path)`: owns the only connection (`check_same_thread=False`), `close()`, context manager.
  On open it runs migrations keyed by `PRAGMA user_version`:
  - v1: `cache(key TEXT PRIMARY KEY, value TEXT NOT NULL, stored_at REAL NOT NULL)` created with
    `IF NOT EXISTS` (so Phase 2 databases, which already have `cache` at user_version 0, upgrade in place).
  - v2: `accounts(handle TEXT PRIMARY KEY, data TEXT NOT NULL)`, `themes(name TEXT PRIMARY KEY, data TEXT NOT NULL)`,
    `history(account TEXT NOT NULL, anilist_id INTEGER NOT NULL, post_id TEXT NOT NULL, exported_at TEXT NOT NULL,
    PRIMARY KEY (account, anilist_id, post_id))`, index on `(account, exported_at)`.
  - `data` columns hold the pydantic model JSON.
  All sqlite3/OS errors → `CacheError` (existing) for cache ops, `StorageError` for the rest.
- It implements: the existing `Cache` port (replaces `SqliteCache`, which is deleted; `CachedChapterSource`
  unchanged), `AccountRepository` (`add`, `update`, `get`, `list`, `remove`), `ThemeRepository` (same),
  `HistoryRepository` (`record(account, post_id, anilist_ids, exported_at)` idempotent,
  `recent(account, since: datetime) -> set[int]`).

## Suggestion flow (`app/suggest.py`)
`suggest_for_account(query, account | None, metadata, chapters, history, now, allow_repeats, progress)`:
1. `query` + account block lists → `exclude_genres`/`exclude_tags`.
2. `recent = history.recent(account, now - repeat_days)` unless no account or `allow_repeats`;
   fetch limit = `min(50, query.limit + len(recent))`.
3. No allow-list → one search. Allow-list → one search per allowed genre (`genres = query.genres + [g]`),
   merged without duplicates (first occurrence wins); sort merged by `score` (SCORE) or `popularity`
   (POPULARITY) descending, `None` scores last; TRENDING keeps round-robin interleave of the lists.
4. Drop `recent` ids, cut to `query.limit`, then the Phase 1 chapter backfill (fail-fast) on what remains.
`suggest_titles` (Phase 1) stays for the `suggest` command; `suggest` gains optional `--account` using the new function.

## Build / export / delete (`app/`)
- `create_post(post_id, now, candidates, title, items, account: Account | None, hashtags, accent) -> ListPost`
  (pure; fills account, cta texts, hashtags/accent from overrides → account → defaults). `build_post`
  uses it; the draft/editor flow is unchanged.
- `FsPostRepository.new_id` reserves the id with `mkdir(exist_ok=False)` (retry on collision).
- `export_post(post_id, posts, history, dest_root, now)`: after copying, if the post has an account and
  no `exported_at`, set it to `now`, save the post, `history.record(...)`. Re-export keeps the first date.
- `delete_post(post_id, posts)`: `shutil.rmtree` of the post folder (errors → `StorageError`); the CLI
  asks for confirmation.
- `container`: `build_store(settings)` (one `SqliteStore` per command), `build_posts(settings)` (repository only,
  used by `export`/`posts`/`delete`); `build_chapter_source` takes the store as its cache.
- Name checking: `MetadataSource` gains `list_genres() -> list[str]` (AniList `GenreCollection`);
  `account add/set` and `theme add` validate genres/tags against AniList lists (cached 24 h in the store
  cache); unknown names → `InvalidName` with up to 3 close matches (`difflib.get_close_matches`); if AniList
  is unreachable, print a warning and save anyway.

## Rendering (style change)
- Fonts: `Montserrat-Variable.ttf` (google/fonts `ofl/montserrat/Montserrat[wght].ttf`) + `OFL-Montserrat.txt`;
  `fonts.display(size)` = weight 900, `fonts.bold(size)` = 800, `fonts.body(size)` = 600. Anton/Inter files
  and their functions are removed.
- Display text stays uppercase. Sizes are re-tuned for Montserrat during prototyping (starting points:
  cover title 92→56, manhwa name 62→42, rank 96, hook 36→28, end title 100→68) and must keep every
  existing layout containment test passing.
- End slide: blur the assembled 2×2 grid once (no seams at x=540/y=960); recap rows are vertically centred
  in the band between the title and the follow line when they don't fill it.

## Testing
- Store: fresh DB migrates to v2; a Phase 2-style DB (cache table, user_version 0, existing rows) migrates
  and keeps its cache rows; repositories round-trip; history `recent` window boundaries; errors wrapped.
- Domain: handle/theme validation, account/theme defaults, ListPost loads a Phase 2 `post.json`.
- Suggestion: block lists passed through, per-genre merge/dedupe/sort, TRENDING interleave, over-fetch and
  repeat filtering, `--allow-repeats`, no-account path unchanged (fakes; no network).
- Export records history once; re-export keeps the first date; delete removes the folder and keeps history.
- CLI: account/theme CRUD incl. errors, build with theme/account (fakes), theme+flags conflict error,
  posts filter, delete confirm/`--yes`, name validation with suggestions, AniList-down warning path.
- Layout containment with Montserrat (extreme inputs, 1/5/33 items); renderer end-slide grid has no seam.
- Live (gated): create a temp account with `--block-genres Romance`, build from a theme, assert no Romance title.

## Out of scope for 3a
TUI (3b), uploading (Phase 4), LLM hooks, per-account fonts, AniList search-response caching.
