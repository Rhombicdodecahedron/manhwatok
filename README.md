# manhwatok

Themed manhwa recommendation slideshows for TikTok accounts.

Find the best Korean manhwa for a theme, then turn the list into a ready-to-upload TikTok photo carousel.

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
24 h in `$XDG_DATA_HOME/manhwatok/manhwatok.db` (default `~/.local/share/manhwatok/manhwatok.db`).
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

Options: `--hashtags "..."` (caption hashtags), `--accent "#43c9e4"` (cover/end slide colour).
Manhwa slides take their accent colour from each cover. Export folder: `--out DIR` or
`MANHWATOK_EXPORT_DIR`. Upload the PNGs as a TikTok photo post and paste `caption.txt`.

Fonts: Anton and Inter, bundled under the SIL Open Font License (`src/manhwatok/assets/fonts/`).

## Tests

```bash
uv run pytest                                        # offline unit tests
MANHWATOK_LIVE=1 uv run pytest tests/integration     # real AniList/MangaUpdates
```
