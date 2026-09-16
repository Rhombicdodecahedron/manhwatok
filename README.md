# manhwatok

Themed manhwa recommendation slideshows for TikTok accounts.

Find the best Korean manhwa for a theme, then turn the list into a ready-to-upload TikTok photo
carousel — for several TikTok accounts, each with its own filters, style and repeat protection.

## Setup

```bash
uv sync
```

## Usage

```bash
uv run manhwatok tags revenge                        # find AniList tags for a theme
uv run manhwatok suggest -t "Time Manipulation" -t Revenge -n 10
uv run manhwatok suggest -g Romance -g Fantasy --sort popularity
uv run manhwatok suggest -t Murim --no-chapters      # skip MangaUpdates lookups
```

Regressor/time-loop stories are tagged "Time Manipulation", not "Age Regression" (that tag means
characters turned younger).

Repeated `-t`/`-g` flags must all match. `--min-tag-rank` (default 60) drops titles where a tag
is only a minor element.

Chapter counts come from AniList when it reports a total (finished series), and from
MangaUpdates for any title AniList has no chapter count for — typically ongoing series — cached
24 h in `$XDG_DATA_HOME/manhwatok/manhwatok.db` (default `~/.local/share/manhwatok/manhwatok.db`;
the same database holds accounts, themes and posting history).
Override the data dir with `MANHWATOK_DATA_DIR`. Pass `--no-chapters` to skip the MangaUpdates
lookup entirely.

## Making a post

```bash
uv run manhwatok build -t "Time Manipulation" -t Revenge \
    --title "Manhwa where the MC *regresses* for *revenge*"
```

`build` finds candidates (same flags as `suggest`) and opens a draft in `$VISUAL`/`$EDITOR`
(falls back to `nano`/`vi`):

```
title: Manhwa where the MC *regresses* for *revenge*
128067 | SSS-Class Revival Hunter | He copies the skill of anyone who kills him.
136220 | Doom Breaker | The last man standing is sent back ten years.
# 116382 | The Villainess Turns the Hourglass | Executed, she wakes up at 13.
```

Delete lines to drop titles, reorder lines to rank them, edit the hook after the second `|`,
and wrap title words in `*stars*` to colour them. Save and close: the slides (cover, one per
manhwa, end slide) and `caption.txt` are rendered into
`$XDG_DATA_HOME/manhwatok/posts/<id>/`. Save as-is to accept the prefilled picks unchanged;
delete everything (or exit the editor with an error, e.g. `:cq` in vim) to cancel. GUI editors
need a wait flag, e.g. `EDITOR="code --wait"`.

```bash
uv run manhwatok posts                 # list posts
uv run manhwatok edit <id>             # change picks/hooks, re-render
uv run manhwatok render <id>           # re-render only
uv run manhwatok export <id>           # copy slides + caption to ~/Downloads/manhwatok/<id>/
```

Options: `--hashtags "..."` (caption hashtags), `--accent "#43c9e4"` (cover/end slide colour);
both default to the account's (see below). Manhwa slides take their accent colour from each cover.
Export folder: `--out DIR` or `MANHWATOK_EXPORT_DIR`. Upload the PNGs as a TikTok photo post and
paste `caption.txt` — or let `manhwatok upload` fill them in for you (see below).

```bash
uv run manhwatok delete <id>           # asks first; --yes skips the question
```

Fonts: Montserrat, bundled under the SIL Open Font License (`src/manhwatok/assets/fonts/`).

## Accounts and themes

Each TikTok account keeps its own genre filters, hashtags, accent colour and end-slide texts.
Themes (tags/genres + title) are shared by every account.

```bash
uv run manhwatok account add @manhwa.daily --genres Action,Fantasy --block-genres Romance \
    --block-tags Harem --hashtags "#manhwa #manhwarec" --accent "#ff5a5f"
uv run manhwatok account set @manhwa.daily --cta-follow "Follow for more"   # only these change
uv run manhwatok account list                     # also: show <handle>, remove <handle>

uv run manhwatok theme add regression-revenge -t "Time Manipulation" -t Revenge \
    --title "Manhwa where the MC *regresses* for *revenge*"
uv run manhwatok theme list                       # also: show <name>, remove <name>

uv run manhwatok build --account @manhwa.daily --theme regression-revenge
uv run manhwatok posts --account @manhwa.daily
```

- `--genres` is an allow-list (a title needs at least one of them); `--block-genres` and
  `--block-tags` are never suggested. List options take comma-separated names; `--genres ""`
  clears a list. Names are checked against AniList ("did you mean …?"); if AniList is down the
  account is saved anyway with a warning.
- A post's titles count as posted when the post is **exported**, dated with its first export
  (titles swapped in by `edit` count once you export again), and again when you confirm an
  `upload` of it, dated then — the later date counts. `build --account` (and `suggest
  --account`) skip titles that account posted in the last `--repeat-days` (default 30);
  `build --allow-repeats` keeps them.
- `--theme` supplies tags, genres, sort, min tag rank and title; `--title`, `--sort` and
  `--min-tag-rank` override it. Use either `--theme` or `-t/-g`, not both.
- Without `--account`, `build` behaves as before: no filters, no history, default hashtags,
  accent and end slide.
- `account remove` keeps the account's posting history, so re-adding the handle keeps its repeat
  protection. `--cta-title` / `--cta-follow` set the end slide's texts (`*word*` = accent colour).

## Uploading to TikTok (assisted)

`upload` takes the manual steps out of posting but leaves the decision to you: it opens a real,
visible Chromium window logged in as the post's account, attaches the slides in order and types
the caption. You check the post (add a sound, pick the cover) and click **Post** yourself.

```bash
uv sync --extra upload && uv run playwright install chromium   # once: Playwright + its Chromium

uv run manhwatok login @manhwa.daily      # once per account: log in by hand, close the window
uv run manhwatok upload <id>              # an account's post with up-to-date slides
```

- Each account gets its own browser profile in `$XDG_DATA_HOME/manhwatok/browser/<handle>/`;
  manhwatok never sees your password. Captchas and login checks are yours to answer in the
  window.
- `upload` prints what it did and anything left for you (e.g. "caption box not found — paste
  caption.txt yourself"), plus the slides folder, then asks `Posted on @x? [y/N]` with the
  window still open. `y` records the post: its titles count as posted for the repeat window and
  `posts` marks it `sent`. Anything else records nothing. The window closes after you answer.
- `upload --debug` saves a screenshot and the page's HTML to
  `$XDG_DATA_HOME/manhwatok/debug/<id>-<time>/` whenever something wasn't found. TikTok changes
  its site now and then; the selectors live in `src/manhwatok/adapters/tiktok_page.py`. The
  saved `page.html` comes from a logged-in TikTok page and can contain account details (IDs,
  nickname, tokens) — check it before sharing it with anyone.
- `account remove` asks whether to delete the account's saved login too (`--yes` does).
- manhwatok never clicks Post, schedules or batch-uploads, and does nothing to hide that the
  browser is automated. Automating TikTok's website is against TikTok's Terms of Service and may
  trigger captchas or account checks — use it at your own risk.

## Songs

TikTok photo posts get their sound in TikTok itself. manhwatok keeps a note of which one to add:
a song name or a TikTok sound link, per account (the default) and per post.

```bash
uv run manhwatok account set @manhwa.daily --song "Die For You – The Weeknd"
uv run manhwatok build --account @manhwa.daily --theme regression-revenge --song "Other song"
uv run manhwatok song <id>                  # show the post's song
uv run manhwatok song <id> "New song"       # set this post's own song ("" = no song)
uv run manhwatok song <id> --clear          # follow the account's song again
```

A post without its own song follows its account's, including later `account set --song` changes.
`posts` shows each post's song (once any post has one), and `upload` prints it right before you
check the post. Songs aren't on the slides or in the caption.

## Terminal app

```bash
uv sync --extra tui          # once (add --extra upload to keep the upload helper)
uv run manhwatok tui
```

Everything the commands above do, in one window with four tabs (`1`–`4`, `q` quits):

- **Posts** — the list, and a preview of the highlighted post: its slides (`←`/`→` flip, `o`
  opens the slide in your image viewer), caption, song and picks. `e` edit picks, `r` render,
  `x` export, `u` upload (`U` with `--debug`), `s` song, `d` delete, `f` show one account's posts.
- **Build** — account, theme or tags/genres, and the post's style; **Search** opens the picks
  editor: `space` picks or drops a title, `shift+↑`/`shift+↓` reorder, `enter` edits a hook,
  `ctrl+s` saves and renders, `esc` cancels. "Find a tag" searches AniList's tags.
- **Accounts** / **Themes** — `a` add, `e` or `enter` edit, `d` remove; `l` logs an account in
  to TikTok.

Slides show as real pictures in terminals with image support (kitty, WezTerm, Konsole, foot and
other sixel terminals); elsewhere as coloured blocks. Uploading works as with `manhwatok upload`:
the log shows what the browser did, and a dialog asks whether you posted it. Only one render and
one browser run at a time; quitting waits for both. The TUI and the commands can be used at the
same time.

## Upgrading from earlier versions

- The database upgrades itself the first time you run any command; cached chapter counts are
  kept.
- Existing posts show `-` in the `posts` account column and don't count toward any account's
  repeat history.
- Re-rendering an old post (`render`, `edit`) uses the new Montserrat style.
- A post keeps the end-slide texts it was built with: a later `account set --cta-title` /
  `--cta-follow` doesn't change existing posts.
- The database switches to WAL mode the first time any command opens it (`manhwatok.db-wal` and
  `manhwatok.db-shm` appear next to it while it's in use). Accounts and posts from earlier
  versions have no song.
- Handles now need at least one letter or digit (TikTok allows no others). An account saved
  earlier with a handle of only `.` and `_` can't be loaded any more: `account list` stops with
  "is unreadable" and `account remove` refuses the handle. Delete it from the database by hand,
  e.g. `sqlite3 ~/.local/share/manhwatok/manhwatok.db "DELETE FROM accounts WHERE handle = '__'"`
  (its posting history is kept, as with `account remove`).

## Tests

```bash
uv run pytest                                        # offline unit tests
MANHWATOK_LIVE=1 uv run pytest tests/integration     # real AniList/MangaUpdates
```

`tests/tui` drives the terminal app headless against fakes; it is skipped unless the tui extra is
installed (`uv sync --extra upload --extra tui` installs both extras).

`tests/browser` (marker `browser`) drives a headless Chromium against local fixture pages — never
tiktok.com. It is skipped unless the upload extra and its Chromium are installed; `-m "not
browser"` skips it anyway.
