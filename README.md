# manhwatok

Themed manhwa recommendation slideshows for TikTok accounts.

Phase 1: find the best Korean manhwa for a theme, with chapter counts.

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

## Tests

```bash
uv run pytest                                        # offline unit tests
MANHWATOK_LIVE=1 uv run pytest tests/integration     # real AniList/MangaUpdates
```
