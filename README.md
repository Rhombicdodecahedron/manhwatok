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
paste `caption.txt`.

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
  (titles swapped in by `edit` count once you export again). `build --account` (and `suggest
  --account`) skip titles that account exported in the last `--repeat-days` (default 30);
  `build --allow-repeats` keeps them.
- `--theme` supplies tags, genres, sort, min tag rank and title; `--title`, `--sort` and
  `--min-tag-rank` override it. Use either `--theme` or `-t/-g`, not both.
- Without `--account`, `build` behaves as before: no filters, no history, default hashtags,
  accent and end slide.
- `account remove` keeps the account's posting history, so re-adding the handle keeps its repeat
  protection. `--cta-title` / `--cta-follow` set the end slide's texts (`*word*` = accent colour).

## Upgrading from earlier versions

- The database upgrades itself the first time you run any command; cached chapter counts are
  kept.
- Existing posts show `-` in the `posts` account column and don't count toward any account's
  repeat history.
- Re-rendering an old post (`render`, `edit`) uses the new Montserrat style.
- A post keeps the end-slide texts it was built with: a later `account set --cta-title` /
  `--cta-follow` doesn't change existing posts.

## Tests

```bash
uv run pytest                                        # offline unit tests
MANHWATOK_LIVE=1 uv run pytest tests/integration     # real AniList/MangaUpdates
```
