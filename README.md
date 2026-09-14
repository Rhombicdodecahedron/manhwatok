# manhwatok

Themed manhwa recommendation slideshows for TikTok accounts.

Phase 1: find the best Korean manhwa for a theme, with chapter counts.

## Setup

```bash
uv sync
```

## Usage

```bash
manhwatok tags regress                        # find AniList tags for a theme
manhwatok suggest -t "Time Manipulation" -t Revenge -n 10
manhwatok suggest -g Romance -g Fantasy --sort popularity
manhwatok suggest -t Murim --no-chapters      # skip MangaUpdates lookups
```

Repeated `-t`/`-g` flags must all match. `--min-tag-rank` (default 60) drops titles where a tag
is only a minor element.

Chapter counts come from AniList for finished series and from MangaUpdates (cached 24 h in
`~/.local/share/manhwatok/manhwatok.db`) for ongoing ones. Override the data dir with
`MANHWATOK_DATA_DIR`.

## Tests

```bash
uv run pytest                                        # offline unit tests
MANHWATOK_LIVE=1 uv run pytest tests/integration     # real AniList/MangaUpdates
```
