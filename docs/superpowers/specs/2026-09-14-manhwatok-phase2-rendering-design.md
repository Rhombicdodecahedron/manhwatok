# manhwatok Phase 2: post building, slide rendering, local export

Parent spec: `2026-09-14-manhwatok-design.md` (Phase 2 of 4). Phase 1 (`suggest`, `tags`) is merged.

## Goal
Turn a theme into a finished TikTok photo-carousel post on disk: pick titles in a draft file,
render 1080×1920 PNG slides (generated cover slide, one slide per manhwa, end slide) plus a
caption, and export them for manual upload. No accounts (Phase 3), no upload (Phase 4).

## Decisions (made with the user, 2026-09-14)
- Build flow: draft file edited in `$EDITOR` (not CLI flags, not a TUI yet).
- Visual style: **C, full-bleed look with blur-fill**. A blurred, darkened cover fills the slide; the sharp
  cover sits on top near native resolution. AniList covers are ~460×650, so a true full-bleed stretch would look soft.
- Accent colour: per manhwa slide from AniList `coverImage.color`, auto-lightened when too dark;
  cover/end slides use the post accent (default `#43c9e4`, `--accent` overrides).
- Hook prefill: first sentence of the AniList synopsis, ≤110 chars. No LLM in Phase 2.
- Storage: one folder per post, `<data_dir>/posts/<id>/` (no SQLite tables yet).

## Commands
```
manhwatok build [-t TAG]... [-g GENRE]... [--sort ...] [-n 12] [--min-tag-rank 60]
                [--title "Manhwa where the MC *regresses* for *revenge*"]
                [--hashtags "#manhwa ..."] [--accent "#43c9e4"]
    suggest (with chapter backfill) → draft in $EDITOR → save → render → print id + folder
manhwatok edit <id>      reopen draft (or the saved broken draft.txt) → save → re-render
manhwatok render <id>    re-render slides + caption from post.json
manhwatok export <id> [--out DIR]   copy NN.png + caption.txt to DIR/<id>/
manhwatok posts          list posts, newest first: id, created date, title (plain), slide count
```
- `build` needs at least one `-t`/`-g` (same rule and flags as `suggest`).
- Default export dir: `$MANHWATOK_EXPORT_DIR`, else `~/Downloads/manhwatok` if `~/Downloads` exists, else `./manhwatok`.
- Default hashtags: `#manhwa #manhwarecommendation #webtoon #manhwatiktok`.
- Post id: `YYYYMMDD-xxxx` (local date + 4 random lowercase hex chars), unique within `posts/`.

## Draft file
```
title: Manhwa where the MC *regresses* for *revenge*
# *word* = accent colour. Delete lines to drop, move lines to reorder, edit text after the 2nd |.
# Order = rank. Lines starting with # are ignored.

128067 | SSS-Class Revival Hunter | He copies the skill of anyone who kills him.
136220 | Doom Breaker | The last man standing is sent back ten years.
# 116382 | The Villainess Turns the Hourglass | Executed, she wakes up at 13.
```
- `render_draft(title, items, candidates)`: header with `title:` (empty if no `--title`), the
  instruction comments, a blank line, the chosen items uncommented in order, then every other
  candidate commented out with `# `. On first build every candidate is uncommented.
- `parse_draft(text, candidates)`: exactly one `title:` line, non-empty after strip; item lines
  split on `|` with maxsplit 2 → `id | name | hook` (name ignored, hook stripped, may be empty);
  id must be an int present in candidates; no duplicate ids; 1 to 33 items (35-slide TikTok cap
  minus cover and end). Violations raise `DraftError` with the 1-based line number.
- Editor contract (as in `minutes`): `EditorFn = Callable[[str], str | None]`, where `None` means
  aborted or unchanged. The CLI uses `adapters/editor.py` `edit_text`, which runs `$VISUAL`, else
  `$EDITOR`, else `nano`/`vi` on a temp file. It avoids `click.edit` because typer 0.27 no longer ships click.
- `build`: editor returns `None` → "cancelled", nothing saved. `DraftError` → post folder is created
  with `draft.txt` (the user's text) and `post.json` holding the candidates and an empty item list;
  the error and "fix with: manhwatok edit <id>" are printed; exit 1.
- `edit`: opens `draft.txt` if present, else `render_draft` from post.json. On success it deletes
  `draft.txt`, saves, and re-renders.
- A post with zero items (its draft failed) is "unfinished": `render`/`export` raise
  `DraftError("post <id> has no items — fix with: manhwatok edit <id>")`; `posts` shows it with
  `draft` instead of a slide count.

## Domain
- `Manhwa` gains `cover_color: str | None = None` (AniList `coverImage { extraLarge color }`).
- `domain/post.py`: `PostItem(manhwa: Manhwa, hook: str)`;
  `ListPost(id: str, created_at: datetime (tz-aware UTC), title: str, items: list[PostItem],
  candidates: list[Manhwa], hashtags: str, accent: str)`; property `slide_count = len(items) + 2`.
- `domain/text.py`:
  - `first_sentence(desc, max_len=110)`: text up to and including the first `.`/`!`/`?` that is followed
    by whitespace or the end, trimmed. If there is no terminator, the whole first line. If longer than
    `max_len`, cut at the last space at or before `max_len - 1` and add `…`. Empty in, empty out.
  - `accent_spans(title) -> list[tuple[str, bool]]`: `*x*` → `(x, True)`, everything else `(…, False)`;
    an unmatched `*` is literal text. `plain_title(title)` removes the markers.
- `domain/color.py` `readable_accent(hex_or_none, default="#43c9e4") -> str`: invalid/None → default;
  otherwise, while WCAG relative luminance < 0.30, raise HLS lightness by 0.05 (up to 0.95), which
  keeps hue and saturation (`#6b1a1a` → `#e28888`; mixing toward white gave grey `#b99292`); returns
  `#rrggbb` lowercase.
- `domain/caption.py` `build_caption(post)`:
  `"{plain_title}\n\n1. {name}\n2. {name}…\n\n{hashtags}"`.

## Rendering (PNG 1080×1920 RGB; safe area x 90–990, y 250–1670)
All text lives in bottom-anchored stacks inside the safe area. `layout.py` does the pure fitting:
wrap by measured width, shrink the font step by step to the minimum, then ellipsize the last line.
It returns boxes so tests can check containment. Fonts: Anton (titles/numbers, uppercase) and
Inter (text, SemiBold/ExtraBold), both OFL, bundled under `src/manhwatok/assets/fonts/` with `OFL.txt`.

- **Background (manhwa and cover slides):** the cover scaled to fill 1080×1920 (center crop), Gaussian blur
  radius 36, brightness 0.42. Bottom gradient over the lowest 920 px: transparent → 88% black at 55% → black.
- **Manhwa slide:** text stack bottom-anchored at y=1670, 24 px gaps, left x=90, right limit x=960:
  - rank `#N`: Anton 120, accent
  - name: Anton 84 → min 56, max 2 lines, white
  - chapter pill: `chapter_label` uppercased, Inter ExtraBold 36, 6 px accent outline, fully rounded
  - hook: Inter SemiBold 40 → min 32, max 3 lines, white; omitted when empty
  The sharp cover fits inside the box from y=250 to (stack top − 40), max 620×876, aspect kept,
  centred horizontally, 24 px rounded corners and a soft shadow.
- **Cover slide:** background from item #1.
  - Fan of up to 3 covers (items 1–3): centre 440×624 at top y=312; sides 416×588 rotated ±11°,
    horizontal centres ±250 px from the middle, top y=384; drawn back to front so the centre is on top.
  - Text stack bottom-anchored at y=1670: kicker pill `N PICKS` (Inter ExtraBold 36, accent background,
    dark text); title Anton 124 → min 72, max 4 lines, `*accent*` spans in the post accent; progress
    bar of N equal segments, 16 px tall, 20 px gaps, first segment in the accent.
- **End slide:** background is a 2×2 grid of the first 4 covers (cycled if fewer), blur 30, brightness 0.30.
  - `WHICH ONE HAVE YOU *READ?*` in Anton 136, centred, top y=480, max 3 lines, accent span.
  - Recap list: number in Anton plus name in Inter SemiBold 44 → min 28, line height 1.9, x 160–920;
    each number in its item's accent. It shrinks to fit between (title bottom + 40) and y=1460.
  - `FOLLOW FOR PART 2` in Inter ExtraBold 48, centred, baseline area y=1500–1560.
- **Missing cover** (download failed): background and sharp cover become a vertical gradient in that
  item's accent colour; a warning is printed; rendering continues.
- `render` deletes existing `NN.png` in the post folder first (slide count may change), writes
  `01.png…NN.png` (cover first, end last) and `caption.txt`.

## Adapters / app
- `adapters/cover_cache.py` `CoverCache(dir, client=None)`: `get(manhwa) -> Path`, cached file
  `<data_dir>/covers/<anilist_id><ext>` (ext from the URL path, default `.jpg`). Downloads with
  `User-Agent: manhwatok/0.1`. Failure raises `MetadataError`; `render_post` turns it into the
  missing-cover path and stops downloading for the rest of that render (one warning).
- `adapters/fs_posts.py` `FsPostRepository(posts_dir)`: `save(post)`, `get(id)` (missing → `PostNotFound`),
  `list()` (newest first), `folder(id)`, `save_draft(id, text)` / `load_draft(id)` / `clear_draft(id)`.
- `adapters/layout.py`: pure fitting helpers. `adapters/pillow_renderer.py` `PillowRenderer()`
  with `render(post, covers: dict[int, Path | None], out_dir) -> list[Path]` (fonts from `adapters/fonts.py`).
- `app/build_post.py`, `edit_post.py`, `render_post.py`, `export_post.py`; the editor, repository,
  renderer and cover cache are injected, bundled as `app/post_tools.py` `PostTools`.
  `container.build_post_tools(settings, editor, progress)` builds the real ones.
- New errors (all `ManhwatokError`): `DraftError`, `PostNotFound`, `NotRendered` (export before render).
- New dependency: `pillow>=10`.

## Testing
- Unit: every domain function (draft round trip and each error, first_sentence edges, accent spans,
  readable_accent incl. `#6b1a1a` lightens and luminance ≥ 0.30, caption).
- Layout: extreme names/hooks/titles (60+ chars, 400-char hook): every box inside the safe area,
  line counts within the max.
- Renderer: slide count = items + 2, every PNG 1080×1920; missing-cover path renders; no pixel goldens.
- Cover cache: `httpx.MockTransport` hit/miss/failure; fs_posts round trip and listing order.
- CLI: build/edit/render/export/posts with a fake editor and fake metadata (no network).
- Live (gated `MANHWATOK_LIVE=1`): build a real 5-item post into a temp dir with a scripted
  editor; assert 7 PNGs and print the folder for visual inspection.

## Out of scope for Phase 2
Accounts/themes/history (Phase 3), TUI (Phase 3), R2/TikTok upload (Phase 4), LLM hooks, video.
