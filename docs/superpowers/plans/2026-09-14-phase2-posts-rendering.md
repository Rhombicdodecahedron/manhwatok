# Phase 2: Post Building, Slide Rendering, Export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `manhwatok build` turns a theme into a finished TikTok photo-carousel post on disk — draft edited in `$EDITOR`, 1080×1920 PNG slides (generated cover slide, one slide per manhwa, end slide) and a caption — plus `edit`, `render`, `export`, `posts`.

**Architecture:** Same ports-and-adapters layout as Phase 1. Pure domain helpers (post model, draft format, text/colour/caption), a pure layout module that fits text into the TikTok safe area and returns boxes, a Pillow renderer that only paints those boxes, one-folder-per-post storage, a cover download cache, and four use cases wired through the lazy composition root.

**Tech Stack:** Python ≥3.12, uv, pydantic v2, httpx, typer, **Pillow** (new), bundled OFL fonts Anton + Inter (variable), pytest.

**Spec:** `docs/superpowers/specs/2026-09-14-manhwatok-phase2-rendering-design.md` (parent: `2026-09-14-manhwatok-design.md`).

**Provenance:** every code block in this plan was run in a scratch copy of the repo before the plan was written: full suite 203 passed / 4 skipped, `ruff check --select F,E9` clean, and the live test rendered a real 5-title post. Use the code verbatim.

## Global Constraints

- Python `>=3.12`; run everything through `uv run`. Runtime deps after this phase: `httpx>=0.27`, `pillow>=10`, `pydantic>=2.7`, `typer>=0.12` — nothing else. Dev: `pytest>=8.0`.
- **Do not import `click`.** typer 0.27 no longer depends on click (it vendors a private copy); the editor is launched by our own `adapters/editor.py`.
- Slides: PNG, RGB, exactly 1080×1920. Safe area x 90–990, y 250–1670; all text inside it. Slide files are `01.png` (cover) … `NN.png` (end slide), plus `caption.txt`.
- Post folder: `<data_dir>/posts/<id>/` with `post.json`, `draft.txt` (only while a draft is broken), slides, `caption.txt`. Post id `YYYYMMDD-xxxx` (local date + 4 lowercase hex). Covers cached in `<data_dir>/covers/<anilist_id><ext>`.
- Export dir: `$MANHWATOK_EXPORT_DIR`, else `~/Downloads/manhwatok` if `~/Downloads` exists, else `./manhwatok`.
- Defaults: accent `#43c9e4`; hashtags `#manhwa #manhwarecommendation #webtoon #manhwatiktok`; max 33 items per post.
- Unit tests never touch the network (`httpx.MockTransport`, fakes). Live tests only with `MANHWATOK_LIVE=1`.
- All user-facing failures are `ManhwatokError` subclasses; the CLI prints `error: …` and exits 1, never a traceback.
- Out of scope, do not add: accounts/themes/history, TUI, uploading, LLM hooks, video, fetching or posting chapter pages.
- Every commit message ends with exactly these two trailer lines (after a blank line):
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01EKMenSqSzzhkBhEk9vLfCh
  ```
- Repo root: `/home/stellaa/Documents/Personal/manhwatok`. Paths below are relative to it.

## Deviations from the spec (decided while prototyping; the spec is updated in the same commit as this plan)
- Accent lightening raises HLS lightness in 0.05 steps (keeps hue and saturation) instead of mixing toward white — mixing turned `#6b1a1a` into grey `#b99292`; HLS gives `#e28888`.
- `CoverCache.get(manhwa) -> Path` raises `MetadataError` on failure (the spec's `Path | None` return was redundant with "failure raises").
- Editor: own `$VISUAL`/`$EDITOR` launcher (see Global Constraints) instead of `click.edit`; same `str | None` contract.
- `app/post_tools.py` added: bundles repository, covers, renderer, editor, progress (`PostTools`) so use cases take one collaborator.
- Cover downloads stop after the first failure in a render (remaining slides use plain backgrounds), mirroring the chapter-lookup fail-fast from Phase 1.

## File Structure

```
src/manhwatok/assets/fonts/     Anton-Regular.ttf, Inter-Variable.ttf, OFL-Anton.txt, OFL-Inter.txt
src/manhwatok/domain/post.py     PostItem, ListPost, DEFAULT_ACCENT, DEFAULT_HASHTAGS, MAX_ITEMS
src/manhwatok/domain/text.py     first_sentence, accent_spans, plain_title
src/manhwatok/domain/color.py    readable_accent, luminance, hex_to_rgb, is_hex_color
src/manhwatok/domain/caption.py  build_caption
src/manhwatok/domain/draft.py    render_draft, parse_draft
src/manhwatok/ports/posts.py     PostRepository, CoverSource, SlideRenderer protocols
src/manhwatok/adapters/fonts.py  anton(size), inter(size, weight), inter_semibold, inter_extrabold
src/manhwatok/adapters/layout.py pure text fitting + item/cover/end slide layouts
src/manhwatok/adapters/pillow_renderer.py  PillowRenderer
src/manhwatok/adapters/fs_posts.py   FsPostRepository
src/manhwatok/adapters/cover_cache.py CoverCache
src/manhwatok/adapters/editor.py  edit_text
src/manhwatok/app/post_tools.py   PostTools, EditorFn, ProgressFn
src/manhwatok/app/render_post.py  render_post, CAPTION_FILE, unfinished_error
src/manhwatok/app/export_post.py  export_post
src/manhwatok/app/build_post.py   build_post
src/manhwatok/app/edit_post.py    edit_post
Modified: domain/models.py, domain/errors.py, adapters/anilist.py, config.py, app/container.py, cli.py, tests/unit/fakes.py, README.md, pyproject.toml, uv.lock
```

---

### Task 1: AniList cover colour

**Files:**
- Modify: `src/manhwatok/domain/models.py` (Manhwa), `src/manhwatok/adapters/anilist.py` (query + `_to_manhwa`)
- Test: `tests/unit/test_anilist.py`

**Interfaces:**
- Produces: `Manhwa.cover_color: str | None = None` (AniList `coverImage.color`, e.g. `"#43c9e4"`, may be absent).

- [ ] **Step 1: Update the tests first.** In `tests/unit/test_anilist.py`:
  1. In `DOOM_BREAKER`, replace the `"coverImage"` entry with:
     ```python
         "coverImage": {
             "extraLarge": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/bx125636.jpg",
             "color": "#43c9e4",
         },
     ```
  2. In `NO_ENGLISH`, add after `"chapters": 135,`:
     ```python
         "coverImage": {"extraLarge": "https://example.test/c.jpg"},
     ```
  3. In `test_search_maps_media_to_manhwa`, after the `cover_url` assertion add:
     ```python
         assert m.cover_color == "#43c9e4"
     ```
  4. In `test_search_falls_back_to_romaji_and_unknown_status`, after `assert m.chapters == 135` add:
     ```python
         assert m.cover_color is None  # AniList omits color for some covers
     ```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_anilist.py -q`
Expected: FAIL — `AttributeError: 'Manhwa' object has no attribute 'cover_color'`.

- [ ] **Step 3: Implement**
  1. `src/manhwatok/domain/models.py`, in `class Manhwa`, directly after `cover_url: str = ""` add:
     ```python
         cover_color: str | None = None
     ```
  2. `src/manhwatok/adapters/anilist.py`: in `_SEARCH` change `coverImage { extraLarge }` to `coverImage { extraLarge color }`; in `_to_manhwa`, directly after the `cover_url=...` argument add:
     ```python
             cover_color=(m.get("coverImage") or {}).get("color"),
     ```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass (74 passed, 3 skipped).

- [ ] **Step 5: Commit** — `feat: fetch AniList cover colour`

---

### Task 2: Pillow and bundled fonts

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)
- Create: `src/manhwatok/assets/fonts/{Anton-Regular.ttf,Inter-Variable.ttf,OFL-Anton.txt,OFL-Inter.txt}`, `src/manhwatok/adapters/fonts.py`
- Test: `tests/unit/test_fonts.py`

**Interfaces:**
- Produces: `fonts.anton(size) -> FreeTypeFont`, `fonts.inter(size, weight=600) -> FreeTypeFont`, `fonts.inter_semibold(size)`, `fonts.inter_extrabold(size)`, constants `SEMIBOLD=600`, `EXTRABOLD=800`. All cached (`lru_cache`), so the same (size, weight) returns the same object.

- [ ] **Step 1: Add Pillow and download the fonts (Google Fonts repo, OFL)**

```bash
uv add "pillow>=10"
mkdir -p src/manhwatok/assets/fonts && cd src/manhwatok/assets/fonts
curl -fsSL -o Anton-Regular.ttf  https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf
curl -fsSL -o OFL-Anton.txt      https://github.com/google/fonts/raw/main/ofl/anton/OFL.txt
curl -fsSL -o Inter-Variable.ttf "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf"
curl -fsSL -o OFL-Inter.txt      https://github.com/google/fonts/raw/main/ofl/inter/OFL.txt
sha256sum Anton-Regular.ttf Inter-Variable.ttf
cd -
```
Expected hashes (verified 2026-09-14):
```
a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab  Anton-Regular.ttf
29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031  Inter-Variable.ttf
```
If a hash differs, the upstream file changed: note it in your report (DONE_WITH_CONCERNS) and continue only if `test_fonts.py` passes.

- [ ] **Step 2: Write the failing test** — `tests/unit/test_fonts.py`:

```python
from manhwatok.adapters.fonts import anton, inter, inter_extrabold, inter_semibold


def test_fonts_load_at_requested_size():
    assert anton(84).size == 84
    assert inter_semibold(40).size == 40


def test_inter_weights_really_differ():
    text = "Hello World"
    assert inter_extrabold(40).getlength(text) > inter_semibold(40).getlength(text)


def test_fonts_are_cached():
    assert anton(84) is anton(84)
    assert inter(40, 600) is inter_semibold(40)
```

- [ ] **Step 3: Run to see it fail**

Run: `uv run pytest tests/unit/test_fonts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.adapters.fonts'`.

- [ ] **Step 4: Implement** — `src/manhwatok/adapters/fonts.py`:

```python
"""Bundled OFL fonts: Anton for display text, Inter (variable) for body text."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from PIL import ImageFont

_DIR = files("manhwatok") / "assets" / "fonts"
SEMIBOLD = 600
EXTRABOLD = 800


@lru_cache(maxsize=None)
def anton(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_DIR / "Anton-Regular.ttf"), size)


@lru_cache(maxsize=None)
def inter(size: int, weight: int = SEMIBOLD) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(_DIR / "Inter-Variable.ttf"), size)
    font.set_variation_by_axes([32, weight])  # axes: optical size 14–32, weight 100–900
    return font


def inter_semibold(size: int) -> ImageFont.FreeTypeFont:
    return inter(size, SEMIBOLD)


def inter_extrabold(size: int) -> ImageFont.FreeTypeFont:
    return inter(size, EXTRABOLD)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit** — `feat: bundle Anton and Inter fonts, add Pillow` (include `uv.lock`, `pyproject.toml`, the four asset files, fonts.py, test).

---

### Task 3: Post model, text, colour and caption helpers

**Files:**
- Create: `src/manhwatok/domain/post.py`, `src/manhwatok/domain/text.py`, `src/manhwatok/domain/color.py`, `src/manhwatok/domain/caption.py`
- Modify: `tests/unit/fakes.py` (add `post()` factory)
- Test: `tests/unit/test_text.py`, `tests/unit/test_color.py`, `tests/unit/test_post.py`

**Interfaces:**
- Consumes: `Manhwa` (with `cover_color`, Task 1).
- Produces:
  - `post.PostItem(manhwa: Manhwa, hook: str = "")`; `post.ListPost(id: str, created_at: datetime, title: str = "", items: list[PostItem] = [], candidates: list[Manhwa] = [], hashtags: str = DEFAULT_HASHTAGS, accent: str = DEFAULT_ACCENT)` with properties `slide_count` (items + 2) and `is_unfinished` (no items); constants `DEFAULT_ACCENT = "#43c9e4"`, `DEFAULT_HASHTAGS`, `MAX_ITEMS = 33`.
  - `text.first_sentence(desc, max_len=110) -> str`, `text.accent_spans(title) -> list[tuple[str, bool]]`, `text.plain_title(title) -> str`.
  - `color.readable_accent(color: str | None, default=DEFAULT_ACCENT) -> str`, `color.luminance(rgb) -> float`, `color.hex_to_rgb(hex) -> tuple[int, int, int]` (raises `ValueError`), `color.is_hex_color(value) -> bool` (requires leading `#`), `color.MIN_LUMINANCE = 0.30`.
  - `caption.build_caption(post) -> str`.
  - `tests.unit.fakes.post(**overrides) -> ListPost` — defaults: id `"20260914-a3f9"`, created_at 2026-09-14 12:00 UTC, title `"Manhwa where the MC *regresses*"`, three items (anilist ids 1–3, titles `"Title N"`, hooks `"Hook N"`), candidates = the items' manhwa.

- [ ] **Step 1: Add the `post()` factory to `tests/unit/fakes.py`.** Add to the imports at the top:
```python
from datetime import datetime, timezone

from manhwatok.domain.post import ListPost, PostItem
```
and append:

```python
def post(**overrides) -> ListPost:
    items = overrides.pop("items", None)
    if items is None:
        items = [
            PostItem(manhwa=manhwa(anilist_id=i, title=f"Title {i}"), hook=f"Hook {i}")
            for i in (1, 2, 3)
        ]
    fields = {
        "id": "20260914-a3f9",
        "created_at": datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
        "title": "Manhwa where the MC *regresses*",
        "items": items,
        "candidates": [item.manhwa for item in items],
    }
    fields.update(overrides)
    return ListPost(**fields)
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/test_text.py`:

```python
import pytest

from manhwatok.domain.text import accent_spans, first_sentence, plain_title


@pytest.mark.parametrize(
    ("desc", "expected"),
    [
        ("Jay's the perfect student. He has straight As.", "Jay's the perfect student."),
        ("Is he back? Yes.", "Is he back?"),
        ("Version 2.0 of the hero arrives. Then more.", "Version 2.0 of the hero arrives."),
        ("No terminator here\nSecond paragraph.", "No terminator here"),
        ("  \n  ", ""),
        ("", ""),
    ],
)
def test_first_sentence(desc, expected):
    assert first_sentence(desc) == expected


def test_first_sentence_cuts_long_text_at_a_word_with_ellipsis():
    desc = "word " * 40 + "end."
    hook = first_sentence(desc, max_len=30)
    assert len(hook) <= 30
    assert hook.endswith("…")
    assert not hook[:-1].endswith(" ")
    assert hook[:-1].split() == ["word"] * len(hook[:-1].split())


def test_first_sentence_cuts_a_single_huge_word():
    hook = first_sentence("x" * 200, max_len=20)
    assert hook == "x" * 19 + "…"


def test_accent_spans_marks_starred_words():
    assert accent_spans("MC *regresses* for *revenge*") == [
        ("MC ", False),
        ("regresses", True),
        (" for ", False),
        ("revenge", True),
    ]


def test_accent_spans_keeps_a_lone_star_literal():
    assert accent_spans("5* rated") == [("5* rated", False)]


def test_plain_title_drops_markers():
    assert plain_title("MC *regresses* for *revenge*") == "MC regresses for revenge"
```

`tests/unit/test_color.py`:

```python
import pytest

from manhwatok.domain.color import (
    MIN_LUMINANCE,
    hex_to_rgb,
    is_hex_color,
    luminance,
    readable_accent,
)
from manhwatok.domain.post import DEFAULT_ACCENT


def test_bright_colour_is_kept_and_lowercased():
    assert readable_accent("#43C9E4") == "#43c9e4"


def test_dark_colour_is_lightened_until_readable():
    out = readable_accent("#6b1a1a")
    assert out != "#6b1a1a"
    assert luminance(hex_to_rgb(out)) >= MIN_LUMINANCE
    r, g, b = hex_to_rgb(out)
    assert r > g and r > b  # still reads as red


def test_dark_red_keeps_its_hue():
    assert readable_accent("#6b1a1a") == "#e28888"


def test_black_becomes_a_readable_grey():
    r, g, b = hex_to_rgb(readable_accent("#000000"))
    assert r == g == b
    assert luminance((r, g, b)) >= MIN_LUMINANCE


@pytest.mark.parametrize("bad", [None, "", "red", "#12345", "43c9e4", "#gggggg"])
def test_invalid_colour_falls_back_to_default(bad):
    assert readable_accent(bad) == DEFAULT_ACCENT


def test_custom_default():
    assert readable_accent(None, default="#ffffff") == "#ffffff"


def test_is_hex_color():
    assert is_hex_color("#43c9e4")
    assert not is_hex_color("43c9e4")
    assert not is_hex_color("#43c9e")


def test_luminance_extremes():
    assert luminance((0, 0, 0)) == 0
    assert luminance((255, 255, 255)) == pytest.approx(1.0)
```

`tests/unit/test_post.py`:

```python
from manhwatok.domain.caption import build_caption
from manhwatok.domain.post import DEFAULT_ACCENT, DEFAULT_HASHTAGS, ListPost
from tests.unit.fakes import post


def test_slide_count_is_items_plus_cover_and_end():
    assert post().slide_count == 5


def test_post_without_items_is_unfinished():
    assert post(items=[]).is_unfinished
    assert not post().is_unfinished


def test_defaults():
    p = post()
    assert p.hashtags == DEFAULT_HASHTAGS
    assert p.accent == DEFAULT_ACCENT


def test_json_round_trip():
    p = post()
    assert ListPost.model_validate_json(p.model_dump_json()) == p


def test_caption_lists_picks_and_hashtags_with_plain_title():
    assert build_caption(post(hashtags="#manhwa #webtoon")) == (
        "Manhwa where the MC regresses\n\n1. Title 1\n2. Title 2\n3. Title 3\n\n#manhwa #webtoon"
    )
```

- [ ] **Step 3: Run to see them fail**

Run: `uv run pytest tests/unit/test_text.py tests/unit/test_color.py tests/unit/test_post.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.domain.post'` (collection error from fakes/tests).

- [ ] **Step 4: Implement**

`src/manhwatok/domain/post.py`:

```python
"""A recommendation-list post: ordered picks with hooks, plus the candidates it was built from."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from manhwatok.domain.models import Manhwa

DEFAULT_ACCENT = "#43c9e4"
DEFAULT_HASHTAGS = "#manhwa #manhwarecommendation #webtoon #manhwatiktok"
MAX_ITEMS = 33  # TikTok photo posts cap at 35 images: cover + items + end slide


class PostItem(BaseModel):
    manhwa: Manhwa
    hook: str = ""


class ListPost(BaseModel):
    id: str
    created_at: datetime
    title: str = ""
    items: list[PostItem] = Field(default_factory=list)
    candidates: list[Manhwa] = Field(default_factory=list)
    hashtags: str = DEFAULT_HASHTAGS
    accent: str = DEFAULT_ACCENT

    @property
    def slide_count(self) -> int:
        return len(self.items) + 2

    @property
    def is_unfinished(self) -> bool:
        return not self.items
```

`src/manhwatok/domain/text.py`:

```python
"""Small text helpers for slides and drafts: hook prefill and *accent* markup."""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_ACCENT = re.compile(r"\*([^*]+)\*")


def first_sentence(desc: str, max_len: int = 110) -> str:
    """First sentence of the first line, cut at a word boundary with '…' if longer than max_len."""
    first_line = desc.strip().split("\n", 1)[0].strip()
    if not first_line:
        return ""
    end = _SENTENCE_END.search(first_line)
    sentence = first_line[: end.end()] if end else first_line
    if len(sentence) <= max_len:
        return sentence
    cut = sentence.rfind(" ", 0, max_len)
    if cut <= 0:
        cut = max_len - 1
    return sentence[:cut].rstrip(" ,;:") + "…"


def accent_spans(title: str) -> list[tuple[str, bool]]:
    """Split `a *b* c` into [("a ", False), ("b", True), (" c", False)]; a lone `*` is literal."""
    spans: list[tuple[str, bool]] = []
    pos = 0
    for m in _ACCENT.finditer(title):
        if m.start() > pos:
            spans.append((title[pos : m.start()], False))
        spans.append((m.group(1), True))
        pos = m.end()
    if pos < len(title):
        spans.append((title[pos:], False))
    return spans


def plain_title(title: str) -> str:
    return "".join(text for text, _ in accent_spans(title))
```

`src/manhwatok/domain/color.py`:

```python
"""Accent colours: keep AniList cover colours readable on the dark slide background."""

from __future__ import annotations

import colorsys
import re

from manhwatok.domain.post import DEFAULT_ACCENT

MIN_LUMINANCE = 0.30
_HEX = re.compile(r"^#([0-9a-fA-F]{6})$")


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance, 0 (black) to 1 (white)."""
    r, g, b = (_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def is_hex_color(value: str) -> bool:
    return bool(_HEX.match(value))


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    m = _HEX.match(color)
    if not m:
        raise ValueError(f"not a #rrggbb colour: {color!r}")
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{c:02x}" for c in rgb)


def readable_accent(color: str | None, default: str = DEFAULT_ACCENT) -> str:
    """Return `color` as lowercase #rrggbb, lightened (same hue and saturation) until its
    luminance reaches MIN_LUMINANCE so it stays readable on the dark slide background."""
    if not color or not _HEX.match(color):
        return default
    rgb = hex_to_rgb(color)
    h, lightness, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    while luminance(rgb) < MIN_LUMINANCE and lightness < 0.95:
        lightness = min(0.95, lightness + 0.05)
        rgb = tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, lightness, s))  # type: ignore[assignment]
    return _to_hex(rgb)
```

`src/manhwatok/domain/caption.py`:

```python
from manhwatok.domain.post import ListPost
from manhwatok.domain.text import plain_title


def build_caption(post: ListPost) -> str:
    """TikTok caption: plain title, numbered picks, hashtags."""
    picks = "\n".join(f"{i}. {item.manhwa.title}" for i, item in enumerate(post.items, 1))
    return f"{plain_title(post.title)}\n\n{picks}\n\n{post.hashtags}"
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit** — `feat: post model, hook/accent text helpers, readable accents, caption`

---

### Task 4: Draft file format and new errors

**Files:**
- Modify: `src/manhwatok/domain/errors.py`
- Create: `src/manhwatok/domain/draft.py`
- Test: `tests/unit/test_draft.py`

**Interfaces:**
- Consumes: `PostItem`, `MAX_ITEMS` (Task 3), `first_sentence` (Task 3), `fakes.manhwa`.
- Produces:
  - `errors.DraftError`, `errors.PostNotFound`, `errors.NotRendered` (all subclass `ManhwatokError`).
  - `draft.render_draft(title: str, items: list[PostItem], candidates: list[Manhwa]) -> str`; `draft.parse_draft(text: str, candidates: list[Manhwa]) -> tuple[str, list[PostItem]]` (raises `DraftError` naming the 1-based line); `draft.HELP`.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_draft.py`:

```python
import pytest

from manhwatok.domain.draft import parse_draft, render_draft
from manhwatok.domain.errors import DraftError
from manhwatok.domain.post import PostItem
from tests.unit.fakes import manhwa

CANDIDATES = [
    manhwa(
        anilist_id=128067, title="SSS-Class Revival Hunter", description="He copies skills. More."
    ),
    manhwa(anilist_id=136220, title="Doom Breaker", description="Last man standing. More."),
    manhwa(
        anilist_id=116382, title="The Villainess Turns the Hourglass", description="Executed. More."
    ),
]


def _items(*pairs):
    by_id = {m.anilist_id: m for m in CANDIDATES}
    return [PostItem(manhwa=by_id[i], hook=h) for i, h in pairs]


def test_render_lists_chosen_items_then_comments_out_the_rest():
    text = render_draft("MC *regresses*", _items((136220, "Sent back.")), CANDIDATES)
    lines = text.splitlines()
    assert lines[0] == "title: MC *regresses*"
    assert lines[1].startswith("# *word* = accent colour")
    assert "136220 | Doom Breaker | Sent back." in lines
    assert "# 128067 | SSS-Class Revival Hunter | He copies skills." in lines
    assert "# 116382 | The Villainess Turns the Hourglass | Executed." in lines
    assert lines.index("136220 | Doom Breaker | Sent back.") < lines.index(
        "# 128067 | SSS-Class Revival Hunter | He copies skills."
    )
    assert text.endswith("\n")


def test_round_trip_keeps_title_order_and_hooks():
    items = _items((136220, "Sent back."), (128067, "Dies, copies, repeats."))
    title, parsed = parse_draft(render_draft("MC *regresses*", items, CANDIDATES), CANDIDATES)
    assert title == "MC *regresses*"
    assert parsed == items


def test_parse_follows_edited_order_hooks_and_ignores_names():
    text = (
        "title:  Best regressors  \n"
        "# comment\n"
        "\n"
        "116382 | whatever the name says | New hook | with a pipe\n"
        "128067|SSS|\n"
    )
    title, items = parse_draft(text, CANDIDATES)
    assert title == "Best regressors"
    assert [(i.manhwa.anilist_id, i.hook) for i in items] == [
        (116382, "New hook | with a pipe"),
        (128067, ""),
    ]


def test_bare_id_line_gets_empty_hook():
    _, items = parse_draft("title: T\n136220\n", CANDIDATES)
    assert items[0].hook == ""


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("136220 | Doom Breaker | x\n", "'title:' line is missing"),
        ("title:   \n136220 | D | x\n", "'title:' line is missing or empty"),
        ("title: T\ntitle: U\n136220 | D | x\n", "line 2: more than one title line"),
        ("title: T\nDoom Breaker | x\n", "line 2: expected '<id> | <name> | <hook>'"),
        ("title: T\n999 | Nope | x\n", "line 2: 999 is not one of this post's candidates"),
        ("title: T\n136220 | D | x\n136220 | D | y\n", "line 3: 136220 is listed twice"),
        ("title: T\n# 136220 | D | x\n", "no titles left"),
    ],
)
def test_parse_errors(text, message):
    with pytest.raises(DraftError, match=message):
        parse_draft(text, CANDIDATES)


def test_parse_rejects_more_than_33_items():
    many = [manhwa(anilist_id=i, title=f"T{i}") for i in range(1, 35)]
    text = "title: T\n" + "".join(f"{m.anilist_id} | {m.title} | h\n" for m in many)
    with pytest.raises(DraftError, match="34 titles"):
        parse_draft(text, many)
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_draft.py -q`
Expected: FAIL — `ImportError: cannot import name 'DraftError'`.

- [ ] **Step 3: Implement.** Append to `src/manhwatok/domain/errors.py`:

```python
class DraftError(ManhwatokError):
    """The edited draft file can't be turned into a post (bad line, no title, no items)."""


class PostNotFound(ManhwatokError):
    """No saved post with that id."""


class NotRendered(ManhwatokError):
    """The post has no slides yet; run `manhwatok render <id>` first."""
```

`src/manhwatok/domain/draft.py`:

```python
"""The editable text form of a post: one title line, then one `id | name | hook` line per pick."""

from __future__ import annotations

from manhwatok.domain.errors import DraftError
from manhwatok.domain.models import Manhwa
from manhwatok.domain.post import MAX_ITEMS, PostItem
from manhwatok.domain.text import first_sentence

HELP = (
    "# *word* = accent colour. Delete lines to drop, move lines to reorder, edit text after the 2nd |.\n"
    "# Order = rank. Lines starting with # are ignored."
)


def _line(m: Manhwa, hook: str) -> str:
    return f"{m.anilist_id} | {m.title} | {hook}"


def render_draft(title: str, items: list[PostItem], candidates: list[Manhwa]) -> str:
    """Chosen items first (in order), then every other candidate commented out."""
    chosen = {item.manhwa.anilist_id for item in items}
    lines = [f"title: {title}", HELP, ""]
    lines += [_line(item.manhwa, item.hook) for item in items]
    lines += [
        "# " + _line(m, first_sentence(m.description))
        for m in candidates
        if m.anilist_id not in chosen
    ]
    return "\n".join(lines) + "\n"


def parse_draft(text: str, candidates: list[Manhwa]) -> tuple[str, list[PostItem]]:
    """Return (title, items) from an edited draft, or raise DraftError naming the bad line."""
    by_id = {m.anilist_id: m for m in candidates}
    title: str | None = None
    items: list[PostItem] = []
    seen: set[int] = set()
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("title:"):
            if title is not None:
                raise DraftError(f"line {n}: more than one title line")
            title = line[len("title:") :].strip()
            continue
        parts = line.split("|", 2)
        try:
            anilist_id = int(parts[0].strip())
        except ValueError:
            raise DraftError(
                f"line {n}: expected '<id> | <name> | <hook>', got {raw.strip()!r}"
            ) from None
        if anilist_id not in by_id:
            raise DraftError(f"line {n}: {anilist_id} is not one of this post's candidates")
        if anilist_id in seen:
            raise DraftError(f"line {n}: {anilist_id} is listed twice")
        seen.add(anilist_id)
        hook = parts[2].strip() if len(parts) == 3 else ""
        items.append(PostItem(manhwa=by_id[anilist_id], hook=hook))
    if not title:
        raise DraftError("the 'title:' line is missing or empty")
    if not items:
        raise DraftError("no titles left — keep at least one line")
    if len(items) > MAX_ITEMS:
        raise DraftError(f"{len(items)} titles — a TikTok post fits at most {MAX_ITEMS}")
    return title, items
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `feat: editable draft format for posts`

---

### Task 5: Post storage (one folder per post) and paths in Settings

**Files:**
- Create: `src/manhwatok/ports/posts.py`, `src/manhwatok/adapters/fs_posts.py`
- Modify: `src/manhwatok/config.py` (replace whole file)
- Test: `tests/unit/test_fs_posts.py`, `tests/unit/test_config.py` (append)

**Interfaces:**
- Consumes: `ListPost` (Task 3), `PostNotFound` (Task 4), `fakes.post`.
- Produces:
  - Protocols in `ports/posts.py`: `PostRepository` (`new_id(today: date) -> str`, `folder(post_id) -> Path`, `save(post)`, `get(post_id) -> ListPost`, `list() -> list[ListPost]`, `save_draft(post_id, text)`, `load_draft(post_id) -> str | None`, `clear_draft(post_id)`), `CoverSource` (`get(manhwa) -> Path`), `SlideRenderer` (`render(post, covers: dict[int, Path | None], out_dir: Path) -> list[Path]`).
  - `FsPostRepository(posts_dir: Path)` implementing `PostRepository`; `folder()` rejects anything not matching `^\d{8}-[0-9a-f]{4}$` with `PostNotFound` (no path traversal); `list()` is newest first and skips corrupt folders; constants `POST_FILE="post.json"`, `DRAFT_FILE="draft.txt"`.
  - `Settings.export_dir: Path` field; properties `Settings.posts_dir`, `Settings.covers_dir`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_fs_posts.py`:

```python
import re
from datetime import date, datetime, timezone

import pytest

from manhwatok.adapters.fs_posts import FsPostRepository
from manhwatok.domain.errors import PostNotFound
from tests.unit.fakes import post


def test_new_id_is_date_plus_hex_and_unique(tmp_path):
    repo = FsPostRepository(tmp_path)
    ids = {repo.new_id(date(2026, 9, 14)) for _ in range(20)}
    assert all(re.fullmatch(r"20260914-[0-9a-f]{4}", i) for i in ids)


def test_new_id_skips_existing_folders(tmp_path, monkeypatch):
    (tmp_path / "20260914-aaaa").mkdir()
    tokens = iter(["aaaa", "bbbb"])
    monkeypatch.setattr("manhwatok.adapters.fs_posts.secrets.token_hex", lambda n: next(tokens))
    assert FsPostRepository(tmp_path).new_id(date(2026, 9, 14)) == "20260914-bbbb"


def test_save_get_round_trip(tmp_path):
    repo = FsPostRepository(tmp_path)
    repo.save(post())
    assert repo.get("20260914-a3f9") == post()
    assert (tmp_path / "20260914-a3f9" / "post.json").is_file()


def test_get_missing_post(tmp_path):
    with pytest.raises(PostNotFound, match="no post 20260914-0000"):
        FsPostRepository(tmp_path).get("20260914-0000")


@pytest.mark.parametrize("bad", ["../etc", "x", "20260914-A3F9", "20260914-a3f9/.."])
def test_malformed_ids_never_touch_the_filesystem(tmp_path, bad):
    with pytest.raises(PostNotFound, match="not a post id"):
        FsPostRepository(tmp_path).folder(bad)


def test_corrupt_post_json(tmp_path):
    folder = tmp_path / "20260914-a3f9"
    folder.mkdir()
    (folder / "post.json").write_text('{"id": 3}')
    with pytest.raises(PostNotFound, match="unreadable"):
        FsPostRepository(tmp_path).get("20260914-a3f9")


def test_list_newest_first_and_skips_corrupt(tmp_path):
    repo = FsPostRepository(tmp_path)
    repo.save(post(id="20260913-0001", created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    repo.save(post(id="20260914-0002", created_at=datetime(2026, 9, 14, tzinfo=timezone.utc)))
    (tmp_path / "20260914-0003").mkdir()
    (tmp_path / "20260914-0003" / "post.json").write_text("garbage")
    assert [p.id for p in repo.list()] == ["20260914-0002", "20260913-0001"]


def test_list_without_posts_dir(tmp_path):
    assert FsPostRepository(tmp_path / "missing").list() == []


def test_draft_save_load_clear(tmp_path):
    repo = FsPostRepository(tmp_path)
    assert repo.load_draft("20260914-a3f9") is None
    repo.save_draft("20260914-a3f9", "title: x\n")
    assert repo.load_draft("20260914-a3f9") == "title: x\n"
    repo.clear_draft("20260914-a3f9")
    repo.clear_draft("20260914-a3f9")  # idempotent
    assert repo.load_draft("20260914-a3f9") is None
```

Append to `tests/unit/test_config.py`:

```python
def test_posts_and_covers_live_in_data_dir():
    s = Settings(data_dir=Path("/x"))
    assert s.posts_dir == Path("/x/posts")
    assert s.covers_dir == Path("/x/covers")


def test_export_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MANHWATOK_EXPORT_DIR", str(tmp_path / "e"))
    assert Settings().export_dir == tmp_path / "e"


def test_export_dir_defaults_to_downloads(monkeypatch, tmp_path):
    monkeypatch.delenv("MANHWATOK_EXPORT_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Downloads").mkdir()
    assert Settings().export_dir == tmp_path / "Downloads" / "manhwatok"


def test_export_dir_falls_back_to_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("MANHWATOK_EXPORT_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert Settings().export_dir == tmp_path / "manhwatok"
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_fs_posts.py tests/unit/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.adapters.fs_posts'` and `AttributeError: 'Settings' object has no attribute 'posts_dir'`.

- [ ] **Step 3: Implement**

`src/manhwatok/ports/posts.py`:

```python
from datetime import date
from pathlib import Path
from typing import Protocol

from manhwatok.domain.models import Manhwa
from manhwatok.domain.post import ListPost


class PostRepository(Protocol):
    def new_id(self, today: date) -> str: ...

    def folder(self, post_id: str) -> Path: ...

    def save(self, post: ListPost) -> None: ...

    def get(self, post_id: str) -> ListPost: ...

    def list(self) -> list[ListPost]: ...

    def save_draft(self, post_id: str, text: str) -> None: ...

    def load_draft(self, post_id: str) -> str | None: ...

    def clear_draft(self, post_id: str) -> None: ...


class CoverSource(Protocol):
    def get(self, manhwa: Manhwa) -> Path: ...


class SlideRenderer(Protocol):
    def render(
        self, post: ListPost, covers: dict[int, Path | None], out_dir: Path
    ) -> list[Path]: ...
```

`src/manhwatok/adapters/fs_posts.py`:

```python
"""Posts on disk: one folder per post with post.json, draft.txt (while broken), slides, caption."""

from __future__ import annotations

import re
import secrets
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from manhwatok.domain.errors import PostNotFound
from manhwatok.domain.post import ListPost

POST_FILE = "post.json"
DRAFT_FILE = "draft.txt"
_ID = re.compile(r"^\d{8}-[0-9a-f]{4}$")


class FsPostRepository:
    def __init__(self, posts_dir: Path) -> None:
        self._dir = posts_dir

    def new_id(self, today: date) -> str:
        while True:
            post_id = f"{today:%Y%m%d}-{secrets.token_hex(2)}"
            if not (self._dir / post_id).exists():
                return post_id

    def folder(self, post_id: str) -> Path:
        if not _ID.match(post_id):
            raise PostNotFound(f"{post_id!r} is not a post id (like 20260914-a3f9)")
        return self._dir / post_id

    def save(self, post: ListPost) -> None:
        folder = self.folder(post.id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / POST_FILE).write_text(post.model_dump_json(indent=2), encoding="utf-8")

    def get(self, post_id: str) -> ListPost:
        path = self.folder(post_id) / POST_FILE
        if not path.is_file():
            raise PostNotFound(f"no post {post_id} — see `manhwatok posts`")
        try:
            return ListPost.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as e:
            raise PostNotFound(
                f"post {post_id} is unreadable: {e.error_count()} invalid fields"
            ) from e

    def list(self) -> list[ListPost]:
        posts = []
        for path in self._dir.glob(f"*/{POST_FILE}") if self._dir.is_dir() else []:
            try:
                posts.append(ListPost.model_validate_json(path.read_text(encoding="utf-8")))
            except ValidationError:
                continue  # a corrupt folder shouldn't hide the others
        return sorted(posts, key=lambda p: p.created_at, reverse=True)

    def save_draft(self, post_id: str, text: str) -> None:
        folder = self.folder(post_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / DRAFT_FILE).write_text(text, encoding="utf-8")

    def load_draft(self, post_id: str) -> str | None:
        path = self.folder(post_id) / DRAFT_FILE
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def clear_draft(self, post_id: str) -> None:
        (self.folder(post_id) / DRAFT_FILE).unlink(missing_ok=True)
```

`src/manhwatok/config.py` (whole file):

```python
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    if env := os.environ.get("MANHWATOK_DATA_DIR"):
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME", "~/.local/share")
    return Path(xdg).expanduser() / "manhwatok"


def _default_export_dir() -> Path:
    if env := os.environ.get("MANHWATOK_EXPORT_DIR"):
        return Path(env).expanduser()
    downloads = Path("~/Downloads").expanduser()
    return (downloads if downloads.is_dir() else Path.cwd()) / "manhwatok"


@dataclass
class Settings:
    data_dir: Path = field(default_factory=_default_data_dir)
    http_timeout: float = 20.0
    chapter_cache_hours: float = 24.0
    export_dir: Path = field(default_factory=_default_export_dir)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "manhwatok.db"

    @property
    def posts_dir(self) -> Path:
        return self.data_dir / "posts"

    @property
    def covers_dir(self) -> Path:
        return self.data_dir / "covers"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `feat: post folders on disk and post/cover/export paths`

---

### Task 6: Cover download cache

**Files:**
- Create: `src/manhwatok/adapters/cover_cache.py`
- Test: `tests/unit/test_cover_cache.py`

**Interfaces:**
- Consumes: `USER_AGENT` from `adapters/anilist.py`, `MetadataError`, `Manhwa.cover_url`.
- Produces: `CoverCache(covers_dir: Path, client: httpx.Client | None = None, timeout: float = 20.0)` implementing `CoverSource`: `get(manhwa) -> Path` (downloads once to `<covers_dir>/<anilist_id><ext>`, ext from URL if one of .jpg/.jpeg/.png/.webp/.gif else `.jpg`; writes via a `.part` file then rename; raises `MetadataError` on missing URL, HTTP ≥400, empty body, or network error).

- [ ] **Step 1: Write the failing test** — `tests/unit/test_cover_cache.py`:

```python
import httpx
import pytest

from manhwatok.adapters.cover_cache import CoverCache
from manhwatok.domain.errors import MetadataError
from tests.unit.fakes import manhwa

URL = "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/bx136220-u9sewv3u02mN.png"


class Cdn:
    def __init__(self, status=200, body=b"\x89PNG fake"):
        self.status, self.body, self.requests = status, body, []

    def __call__(self, request):
        self.requests.append(request)
        return httpx.Response(self.status, content=self.body)


def _cache(tmp_path, cdn):
    return CoverCache(tmp_path / "covers", client=httpx.Client(transport=httpx.MockTransport(cdn)))


def test_downloads_once_then_serves_from_disk(tmp_path):
    cdn = Cdn()
    cache = _cache(tmp_path, cdn)
    m = manhwa(anilist_id=136220, cover_url=URL)
    first = cache.get(m)
    second = cache.get(m)
    assert first == second == tmp_path / "covers" / "136220.png"
    assert first.read_bytes() == b"\x89PNG fake"
    assert len(cdn.requests) == 1
    assert cdn.requests[0].headers["User-Agent"] == "manhwatok/0.1"
    assert not list((tmp_path / "covers").glob("*.part"))


def test_unknown_extension_saved_as_jpg(tmp_path):
    path = _cache(tmp_path, Cdn()).get(manhwa(anilist_id=5, cover_url="https://x.test/cover"))
    assert path.name == "5.jpg"


def test_http_error_raises_and_writes_nothing(tmp_path):
    with pytest.raises(MetadataError, match="HTTP 404"):
        _cache(tmp_path, Cdn(status=404)).get(manhwa(title="Doom Breaker", cover_url=URL))
    assert not (tmp_path / "covers").exists() or not any((tmp_path / "covers").iterdir())


def test_network_error_raises(tmp_path):
    def down(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(MetadataError, match="cover download failed for Doom Breaker"):
        _cache(tmp_path, down).get(manhwa(title="Doom Breaker", cover_url=URL))


def test_missing_cover_url(tmp_path):
    with pytest.raises(MetadataError, match="no cover image"):
        _cache(tmp_path, Cdn()).get(manhwa(cover_url=""))
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_cover_cache.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.adapters.cover_cache'`.

- [ ] **Step 3: Implement** — `src/manhwatok/adapters/cover_cache.py`:

```python
"""Downloads AniList cover images once and keeps them under <data_dir>/covers/."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import httpx

from manhwatok.adapters.anilist import USER_AGENT
from manhwatok.domain.errors import MetadataError
from manhwatok.domain.models import Manhwa

_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class CoverCache:
    def __init__(
        self, covers_dir: Path, client: httpx.Client | None = None, timeout: float = 20.0
    ) -> None:
        self._dir = covers_dir
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def get(self, manhwa: Manhwa) -> Path:
        """Local path of the cover, downloading it on first use. Raises MetadataError on failure."""
        if not manhwa.cover_url:
            raise MetadataError(f"{manhwa.title}: AniList has no cover image")
        ext = PurePosixPath(urlparse(manhwa.cover_url).path).suffix.lower()
        path = self._dir / f"{manhwa.anilist_id}{ext if ext in _EXTENSIONS else '.jpg'}"
        if path.is_file() and path.stat().st_size > 0:
            return path
        try:
            resp = self._client.get(manhwa.cover_url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as e:
            raise MetadataError(f"cover download failed for {manhwa.title}: {e}") from e
        if resp.status_code >= 400 or not resp.content:
            raise MetadataError(
                f"cover download failed for {manhwa.title}: HTTP {resp.status_code}"
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".part")
        partial.write_bytes(resp.content)
        partial.replace(path)
        return path
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `feat: cache AniList cover images on disk`

---

### Task 7: Editor launcher

**Files:**
- Create: `src/manhwatok/adapters/editor.py`
- Test: `tests/unit/test_editor.py`

**Interfaces:**
- Consumes: `ManhwatokError`.
- Produces: `edit_text(text: str, suffix: str = ".txt") -> str | None` — runs `$VISUAL`, else `$EDITOR` (split with `shlex`), else `nano`, else `vi`, on a temp file; returns the edited text, or `None` if the editor exited non-zero or the text is unchanged; always deletes the temp file; raises `ManhwatokError` if no editor exists or it can't be started.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_editor.py` (it uses a tiny Python script as the fake editor, so no terminal UI is involved):

```python
import os
import shlex
import sys

import pytest

from manhwatok.adapters.editor import edit_text
from manhwatok.domain.errors import ManhwatokError


def _editor(monkeypatch, tmp_path, script: str):
    """Point $EDITOR at a tiny Python script that receives the file path as argv[1]."""
    path = tmp_path / "fake_editor.py"
    path.write_text(script)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", f"{shlex.quote(sys.executable)} {shlex.quote(str(path))}")


def test_returns_edited_text(monkeypatch, tmp_path):
    _editor(monkeypatch, tmp_path, "import sys\nopen(sys.argv[1], 'a').write('added\\n')\n")
    assert edit_text("hello\n") == "hello\nadded\n"


def test_unchanged_text_means_none(monkeypatch, tmp_path):
    _editor(monkeypatch, tmp_path, "pass\n")
    assert edit_text("hello\n") is None


def test_editor_failure_means_none(monkeypatch, tmp_path):
    _editor(monkeypatch, tmp_path, "import sys\nopen(sys.argv[1], 'a').write('x')\nsys.exit(1)\n")
    assert edit_text("hello\n") is None


def test_visual_wins_over_editor(monkeypatch, tmp_path):
    _editor(monkeypatch, tmp_path, "pass\n")
    script = tmp_path / "visual.py"
    script.write_text("import sys\nopen(sys.argv[1], 'w').write('from visual')\n")
    monkeypatch.setenv("VISUAL", f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}")
    assert edit_text("hello") == "from visual"


def test_temp_file_is_removed(monkeypatch, tmp_path):
    _editor(monkeypatch, tmp_path, "import sys\nopen('seen.txt', 'w').write(sys.argv[1])\n")
    monkeypatch.chdir(tmp_path)
    edit_text("hello")
    seen = (tmp_path / "seen.txt").read_text()
    assert seen.endswith(".txt")
    assert not os.path.exists(seen)


def test_missing_editor_binary(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "definitely-not-an-editor-xyz")
    with pytest.raises(ManhwatokError, match="could not start editor"):
        edit_text("hello")


def test_no_editor_configured_or_installed(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr("manhwatok.adapters.editor.shutil.which", lambda name: None)
    with pytest.raises(ManhwatokError, match="set \\$EDITOR"):
        edit_text("hello")
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_editor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.adapters.editor'`.

- [ ] **Step 3: Implement** — `src/manhwatok/adapters/editor.py`:

```python
"""Open text in the user's editor ($VISUAL, $EDITOR, else nano/vi) and read it back."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from manhwatok.domain.errors import ManhwatokError


def _editor_command() -> list[str]:
    for var in ("VISUAL", "EDITOR"):
        if cmd := os.environ.get(var, "").strip():
            return shlex.split(cmd)
    for fallback in ("nano", "vi"):
        if shutil.which(fallback):
            return [fallback]
    raise ManhwatokError("no text editor found — set $EDITOR (e.g. export EDITOR=nano)")


def edit_text(text: str, suffix: str = ".txt") -> str | None:
    """Return the edited text, or None if the editor failed or nothing was changed."""
    command = _editor_command()
    fd, name = tempfile.mkstemp(prefix="manhwatok-", suffix=suffix)
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            result = subprocess.run([*command, str(path)])
        except OSError as e:
            raise ManhwatokError(f"could not start editor {command[0]!r}: {e}") from e
        if result.returncode != 0:
            return None
        edited = path.read_text(encoding="utf-8")
        return None if edited == text else edited
    finally:
        path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `feat: open drafts in $VISUAL/$EDITOR`

---

### Task 8: Slide layout (pure text fitting)

**Files:**
- Create: `src/manhwatok/adapters/layout.py`
- Test: `tests/unit/test_layout.py`

**Interfaces:**
- Consumes: `fonts.anton`, `fonts.inter_semibold`, `fonts.inter_extrabold` (Task 2), `text.accent_spans` (Task 3).
- Produces (all used by the renderer in Task 9):
  - Constants `SLIDE_W=1080`, `SLIDE_H=1920`, `GAP=24`, `PILL_PAD_X=28`, `PILL_PAD_Y=16`, `PILL_BORDER=6`, `BAR_H=16`, `SAFE=Box(90, 250, 900, 1420)`.
  - `Box(x, y, w, h)` with `right`, `bottom`, `contains(other)`; `Word = tuple[str, bool]`.
  - `FittedText(lines, font, line_height)` with `line_text(i)`, `line_width(i)`, `width`, `ink_top`, `ink_bottom`, `height`, `baselines(top)`.
  - `Placed(text, x, y, w, align="left")` with `box`, `line_x(i)`; `Pill(text, box)` with `text_top`.
  - `words_of(spans)`, `plain_words(text)`, `wrap_words(words, font, max_width)`, `fit_words(words, font_for, max_width, max_lines, size, min_size, line_spacing=1.05)`, `stack_up(heights, bottom, gap=GAP)`, `make_pill(...)`, `fit_inside(img_w, img_h, area) -> Box`.
  - `layout_item(rank, name, pill_label, hook) -> ItemLayout(rank, name, pill, hook | None, cover_area)`; `layout_cover(title, count) -> CoverLayout(kicker, title, bar)`; `layout_end(names) -> EndLayout(title, rows: list[EndRow(number | None, name)], follow)`. Each layout has `text_boxes() -> list[Box]`.

Layout rules (from the spec): manhwa slide text is stacked upward from y=1670 (rank Anton 120; name Anton 84→56, ≤2 lines; chapter pill Inter ExtraBold 36; hook Inter SemiBold 40→32, ≤3 lines), cover fitted in `x 230–850, y 250 → (stack top − 40)`, max 620×876. Cover slide: kicker pill `N PICKS`, title Anton 124→72 ≤4 lines with `*accent*` words, progress bar of N segments. End slide: `WHICH ONE HAVE YOU *READ?*` Anton 136→96 centred at y=480, recap rows (number + name, size 44→28, pitch 1.9×size) between title+40 and y=1460 — rows that don't fit collapse into a final `+N more` row, `FOLLOW FOR PART 2` ending at y=1560.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_layout.py`:

```python
import pytest

from manhwatok.adapters.fonts import anton, inter_semibold
from manhwatok.adapters.layout import (
    SAFE,
    Box,
    fit_inside,
    fit_words,
    layout_cover,
    layout_end,
    layout_item,
    plain_words,
    stack_up,
    words_of,
    wrap_words,
)
from manhwatok.domain.text import accent_spans

LONG_NAME = "The Reincarnated Assassin Who Became the Strongest Swordmaster of the Northern Duchy"
LONG_HOOK = "He wakes up again " * 25


def test_stack_up_ends_at_bottom_with_gaps():
    assert stack_up([10, 20, 30], bottom=100, gap=5) == [30, 45, 70]


def test_wrap_respects_width_and_breaks_huge_words():
    font = inter_semibold(40)
    lines = wrap_words(plain_words("short words " * 10 + "x" * 80), font, 400)
    assert all(font.getlength(" ".join(w for w, _ in line)) <= 400 for line in lines)
    assert "".join(w for line in lines for w, _ in line).count("x") == 80


def test_fit_shrinks_before_giving_up():
    fitted = fit_words(plain_words(LONG_NAME.upper()), anton, 870, 2, 84, 56)
    assert len(fitted.lines) <= 2
    assert fitted.font.size < 84


def test_fit_ellipsizes_at_min_size():
    fitted = fit_words(plain_words(LONG_HOOK), inter_semibold, 870, 3, 40, 32)
    assert fitted.font.size == 32
    assert len(fitted.lines) == 3
    assert fitted.line_text(2).endswith("…")
    assert fitted.width <= 870


def test_accent_flags_survive_wrapping():
    fitted = fit_words(
        words_of(accent_spans("MC *REGRESSES* FOR *REVENGE*")), anton, 900, 4, 124, 72
    )
    flags = {w: a for line in fitted.lines for w, a in line}
    assert flags == {"MC": False, "REGRESSES": True, "FOR": False, "REVENGE": True}


def test_fit_inside_keeps_aspect_centred_top_aligned():
    box = fit_inside(460, 650, Box(230, 250, 620, 700))
    assert box.h == 700
    assert box.w == round(460 * 700 / 650)
    assert box.y == 250
    assert box.x == 230 + (620 - box.w) // 2


@pytest.mark.parametrize(
    ("name", "hook"),
    [("Kubera", ""), ("Doom Breaker", "Sent back ten years."), (LONG_NAME, LONG_HOOK)],
)
def test_item_layout_stays_in_safe_area(name, hook):
    layout = layout_item(33, name, "ongoing · ch. 1234", hook)
    assert all(SAFE.contains(b) for b in layout.text_boxes())
    assert layout.cover_area.y == SAFE.y
    assert layout.cover_area.bottom <= layout.rank.box.y - 40
    assert (layout.hook is None) == (hook == "")


def test_item_text_is_bottom_anchored():
    layout = layout_item(1, "Kubera", "ongoing", "A hook.")
    assert layout.hook.box.bottom == SAFE.bottom


@pytest.mark.parametrize("count", [1, 5, 33])
def test_cover_layout_stays_in_safe_area(count):
    layout = layout_cover("*" + LONG_NAME + "* and " + LONG_NAME, count)
    assert all(SAFE.contains(b) for b in layout.text_boxes())
    assert len(layout.bar) == count
    assert len(layout.title.text.lines) <= 4


@pytest.mark.parametrize("n", [1, 5, 33])
def test_end_layout_stays_in_safe_area(n):
    layout = layout_end([LONG_NAME] * n)
    assert all(SAFE.contains(b) for b in layout.text_boxes())


def test_end_layout_collapses_overflow_into_more_row():
    layout = layout_end([f"Title {i}" for i in range(33)])
    last = layout.rows[-1]
    assert last.number is None
    assert last.name.text.line_text(0).startswith("+")
    shown = len(layout.rows) - 1
    assert last.name.text.line_text(0) == f"+{33 - shown} more"


def test_end_layout_uses_big_text_for_short_lists():
    layout = layout_end(["A", "B"])
    assert layout.rows[0].name.text.font.size == 44
    assert [r.number.text.line_text(0) for r in layout.rows] == ["1", "2"]
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_layout.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.adapters.layout'`.

- [ ] **Step 3: Implement** — `src/manhwatok/adapters/layout.py`:

```python
"""Pure slide layout: fit text into boxes and stack it inside the TikTok safe area.

Nothing here draws. Every function returns positions (in 1080×1920 slide pixels) so the
renderer can paint them and tests can check that everything stays inside SAFE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from PIL.ImageFont import FreeTypeFont

from manhwatok.adapters.fonts import anton, inter_extrabold, inter_semibold
from manhwatok.domain.text import accent_spans

SLIDE_W, SLIDE_H = 1080, 1920
GAP = 24
PILL_PAD_X, PILL_PAD_Y, PILL_BORDER = 28, 16, 6
END_TITLE = "Which one have you *read?*"
FOLLOW = "Follow for part 2"

Word = tuple[str, bool]  # (text, accent)
FontFor = Callable[[int], FreeTypeFont]


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def contains(self, other: Box) -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and other.right <= self.right
            and other.bottom <= self.bottom
        )


SAFE = Box(90, 250, 900, 1420)  # x 90–990, y 250–1670


def words_of(spans: list[tuple[str, bool]]) -> list[Word]:
    return [(w, accent) for text, accent in spans for w in text.split()]


def plain_words(text: str) -> list[Word]:
    return [(w, False) for w in text.split()]


def _join(words: list[Word] | tuple[Word, ...]) -> str:
    return " ".join(w for w, _ in words)


@dataclass(frozen=True)
class FittedText:
    lines: tuple[tuple[Word, ...], ...]
    font: FreeTypeFont
    line_height: int

    def line_text(self, i: int) -> str:
        return _join(self.lines[i])

    def line_width(self, i: int) -> int:
        return math.ceil(self.font.getlength(self.line_text(i)))

    @property
    def width(self) -> int:
        return max((self.line_width(i) for i in range(len(self.lines))), default=0)

    @property
    def ink_top(self) -> int:
        """Offset from the first baseline up to the top of the ink (negative)."""
        return self.font.getbbox(self.line_text(0), anchor="ls")[1] if self.lines else 0

    @property
    def ink_bottom(self) -> int:
        """Offset from the last baseline down to the bottom of the ink."""
        return (
            self.font.getbbox(self.line_text(len(self.lines) - 1), anchor="ls")[3]
            if self.lines
            else 0
        )

    @property
    def height(self) -> int:
        if not self.lines:
            return 0
        return (len(self.lines) - 1) * self.line_height + self.ink_bottom - self.ink_top

    def baselines(self, top: int) -> list[int]:
        first = top - self.ink_top
        return [first + i * self.line_height for i in range(len(self.lines))]


def _break_word(word: Word, font: FreeTypeFont, max_width: int) -> list[Word]:
    text, accent = word
    if font.getlength(text) <= max_width:
        return [word]
    pieces, current = [], ""
    for ch in text:
        if current and font.getlength(current + ch) > max_width:
            pieces.append((current, accent))
            current = ch
        else:
            current += ch
    if current:
        pieces.append((current, accent))
    return pieces


def wrap_words(words: list[Word], font: FreeTypeFont, max_width: int) -> list[list[Word]]:
    lines: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        for piece in _break_word(word, font, max_width):
            if current and font.getlength(_join(current + [piece])) > max_width:
                lines.append(current)
                current = [piece]
            else:
                current = current + [piece]
    if current:
        lines.append(current)
    return lines


def _ellipsize(line: list[Word], font: FreeTypeFont, max_width: int) -> list[Word]:
    words = list(line)
    while words:
        text, accent = words[-1]
        candidate = words[:-1] + [(text + "…", accent)]
        if font.getlength(_join(candidate)) <= max_width:
            return candidate
        trimmed = text[:-1].rstrip()
        if trimmed:
            words[-1] = (trimmed, accent)
        else:
            words.pop()
    return [("…", False)]


def fit_words(
    words: list[Word],
    font_for: FontFor,
    max_width: int,
    max_lines: int,
    size: int,
    min_size: int,
    line_spacing: float = 1.05,
) -> FittedText:
    """Largest size (step 4, down to min_size) whose wrap fits max_lines; else ellipsize at min_size."""
    s = size
    while True:
        font = font_for(s)
        lines = wrap_words(words, font, max_width)
        if len(lines) <= max_lines or s <= min_size:
            break
        s = max(min_size, s - 4)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(lines[-1], font, max_width)
    return FittedText(tuple(tuple(line) for line in lines), font, round(s * line_spacing))


def stack_up(heights: list[int], bottom: int, gap: int = GAP) -> list[int]:
    """Top y of each block when stacked upward so the last block ends at `bottom`."""
    tops: list[int] = []
    y = bottom
    for h in reversed(heights):
        y -= h
        tops.append(y)
        y -= gap
    return list(reversed(tops))


@dataclass(frozen=True)
class Placed:
    text: FittedText
    x: int
    y: int  # top of the ink
    w: int  # region width; lines are left-aligned or centred inside it
    align: str = "left"

    @property
    def box(self) -> Box:
        return Box(self.x, self.y, self.w, self.text.height)

    def line_x(self, i: int) -> int:
        if self.align == "center":
            return self.x + (self.w - self.text.line_width(i)) // 2
        return self.x


@dataclass(frozen=True)
class Pill:
    text: FittedText
    box: Box  # outer box incl. padding and border

    @property
    def text_top(self) -> int:
        return self.box.y + PILL_PAD_Y


def make_pill(label: str, font_for: FontFor, size: int, max_width: int, x: int, y: int = 0) -> Pill:
    text = fit_words(
        plain_words(label), font_for, max_width - 2 * PILL_PAD_X, 1, size, size - 8, 1.0
    )
    return Pill(text, Box(x, y, text.width + 2 * PILL_PAD_X, text.height + 2 * PILL_PAD_Y))


def _at(pill: Pill, y: int) -> Pill:
    return Pill(pill.text, Box(pill.box.x, y, pill.box.w, pill.box.h))


def fit_inside(img_w: int, img_h: int, area: Box) -> Box:
    """Largest box with the image's aspect inside `area`, centred horizontally, top-aligned."""
    scale = min(area.w / img_w, area.h / img_h)
    w, h = max(1, round(img_w * scale)), max(1, round(img_h * scale))
    return Box(area.x + (area.w - w) // 2, area.y, w, h)


# --- manhwa slide -------------------------------------------------------------------------

ITEM_TEXT_W = 870  # x 90–960 (keeps clear of TikTok's right-hand buttons)
COVER_MAX_W, COVER_MAX_H = 620, 876


@dataclass(frozen=True)
class ItemLayout:
    rank: Placed
    name: Placed
    pill: Pill
    hook: Placed | None
    cover_area: Box  # the sharp cover is fitted inside this box

    def text_boxes(self) -> list[Box]:
        boxes = [self.rank.box, self.name.box, self.pill.box]
        return boxes + ([self.hook.box] if self.hook else [])


def layout_item(rank: int, name: str, pill_label: str, hook: str) -> ItemLayout:
    x = SAFE.x
    rank_t = fit_words(plain_words(f"#{rank}"), anton, ITEM_TEXT_W, 1, 120, 120)
    name_t = fit_words(plain_words(name.upper() or "?"), anton, ITEM_TEXT_W, 2, 84, 56, 1.04)
    pill = make_pill(pill_label.upper(), inter_extrabold, 36, ITEM_TEXT_W, x)
    hook_t = (
        fit_words(plain_words(hook), inter_semibold, ITEM_TEXT_W, 3, 40, 32, 1.32)
        if hook.strip()
        else None
    )
    heights = [rank_t.height, name_t.height, pill.box.h] + ([hook_t.height] if hook_t else [])
    tops = stack_up(heights, SAFE.bottom)
    cover_bottom = tops[0] - 40
    area_h = max(1, min(COVER_MAX_H, cover_bottom - SAFE.y))
    return ItemLayout(
        rank=Placed(rank_t, x, tops[0], ITEM_TEXT_W),
        name=Placed(name_t, x, tops[1], ITEM_TEXT_W),
        pill=_at(pill, tops[2]),
        hook=Placed(hook_t, x, tops[3], ITEM_TEXT_W) if hook_t else None,
        cover_area=Box((SLIDE_W - COVER_MAX_W) // 2, SAFE.y, COVER_MAX_W, area_h),
    )


# --- cover slide --------------------------------------------------------------------------

BAR_H, BAR_GAP = 16, 20


@dataclass(frozen=True)
class CoverLayout:
    kicker: Pill
    title: Placed
    bar: list[Box]

    def text_boxes(self) -> list[Box]:
        return [self.kicker.box, self.title.box, *self.bar]


def layout_cover(title: str, count: int) -> CoverLayout:
    x, w = SAFE.x, SAFE.w
    kicker = make_pill(f"{count} PICKS", inter_extrabold, 36, w, x)
    title_t = fit_words(words_of(accent_spans(title.upper())), anton, w, 4, 124, 72, 1.02)
    tops = stack_up([kicker.box.h, title_t.height, BAR_H], SAFE.bottom)
    seg_w = (w - BAR_GAP * (count - 1)) / max(count, 1)
    bar = [
        Box(round(x + i * (seg_w + BAR_GAP)), tops[2], max(1, round(seg_w)), BAR_H)
        for i in range(count)
    ]
    return CoverLayout(_at(kicker, tops[0]), Placed(title_t, x, tops[1], w), bar)


# --- end slide ----------------------------------------------------------------------------

LIST_X, LIST_RIGHT, LIST_BOTTOM = 160, 920, 1460
FOLLOW_BOTTOM = 1560


@dataclass(frozen=True)
class EndRow:
    number: Placed | None
    name: Placed


@dataclass(frozen=True)
class EndLayout:
    title: Placed
    rows: list[EndRow]
    follow: Placed

    def text_boxes(self) -> list[Box]:
        boxes = [self.title.box, self.follow.box]
        for row in self.rows:
            boxes += ([row.number.box] if row.number else []) + [row.name.box]
        return boxes


def layout_end(names: list[str]) -> EndLayout:
    x, w = SAFE.x, SAFE.w
    title_t = fit_words(words_of(accent_spans(END_TITLE.upper())), anton, w, 3, 136, 96, 1.02)
    title = Placed(title_t, x, 480, w, "center")
    follow_t = fit_words(plain_words(FOLLOW.upper()), inter_extrabold, w, 1, 48, 48)
    follow = Placed(follow_t, x, FOLLOW_BOTTOM - follow_t.height, w, "center")

    top = title.box.bottom + 40
    avail = LIST_BOTTOM - top
    size = 28
    for s in range(44, 27, -2):
        if round(s * 1.9) * len(names) <= avail:
            size = s
            break
    pitch = round(size * 1.9)
    max_rows = max(1, avail // pitch)
    shown: list[tuple[str | None, str]] = [(str(i), n) for i, n in enumerate(names, 1)]
    if len(shown) > max_rows:
        rest = len(shown) - (max_rows - 1)
        shown = shown[: max_rows - 1] + [(None, f"+{rest} more")]

    num_font = anton(size)
    num_col = math.ceil(num_font.getlength(str(len(names)))) + 24
    name_w = LIST_RIGHT - LIST_X - num_col
    rows: list[EndRow] = []
    for i, (num, name) in enumerate(shown):
        name_t = fit_words(plain_words(name), inter_semibold, name_w, 1, size, size)
        num_t = fit_words(plain_words(num), anton, num_col, 1, size, size) if num else None
        # shared baseline so the Anton number and Inter name sit on one line
        ascent = max(-name_t.ink_top, -(num_t.ink_top if num_t else 0))
        baseline = top + i * pitch + ascent
        rows.append(
            EndRow(
                Placed(num_t, LIST_X, baseline + num_t.ink_top, num_col) if num_t else None,
                Placed(name_t, LIST_X + num_col, baseline + name_t.ink_top, name_w),
            )
        )
    return EndLayout(title, rows, follow)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `feat: pure slide layout with safe-area text fitting`

---

### Task 9: Pillow renderer

**Files:**
- Create: `src/manhwatok/adapters/pillow_renderer.py`
- Modify: `tests/unit/fakes.py` (add `cover_file()`)
- Test: `tests/unit/test_pillow_renderer.py`

**Interfaces:**
- Consumes: everything in `layout.py` (Task 8), `readable_accent`/`hex_to_rgb` (Task 3), `chapter_label` (Phase 1), `ListPost`.
- Produces: `PillowRenderer().render(post, covers: dict[int, Path | None], out_dir) -> list[Path]` implementing `SlideRenderer` — deletes old `NN.png` in `out_dir`, writes `01.png` (cover), one per item, and the end slide; a `None` or unreadable cover path renders an accent-gradient stand-in. Also `tests.unit.fakes.cover_file(folder, anilist_id, color=(200, 60, 60), size=(460, 650)) -> Path` (writes a real JPEG).

Drawing recipe (from the spec): background = cover centre-cropped to 1080×1920, blurred (radius 36, done at quarter size for speed), brightness 0.42; sharp cover with 24 px rounded corners and soft shadow; bottom 920 px gradient transparent → 88% black at 55% → black; accent per manhwa slide = `readable_accent(cover_color, post.accent)`; cover slide fans up to 3 covers (centre 440×624 at y=312, sides 416×588 rotated ±11° at x centre ±250, y=384); end slide = 2×2 grid of the first 4 covers (cycled), blur 30, brightness 0.30.

- [ ] **Step 1: Add `cover_file()` to `tests/unit/fakes.py`.** Add `from pathlib import Path` to the imports and append:

```python
def cover_file(folder: Path, anilist_id: int, color=(200, 60, 60), size=(460, 650)) -> Path:
    """A real (tiny) JPEG so Pillow-based code can open it."""
    from PIL import Image

    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{anilist_id}.jpg"
    Image.new("RGB", size, color).save(path)
    return path
```

- [ ] **Step 2: Write the failing test** — `tests/unit/test_pillow_renderer.py`:

```python
from PIL import Image

from manhwatok.adapters.pillow_renderer import PillowRenderer
from manhwatok.domain.color import hex_to_rgb, readable_accent
from manhwatok.domain.post import PostItem
from tests.unit.fakes import cover_file, manhwa, post


def _post(n=3):
    items = [
        PostItem(
            manhwa=manhwa(anilist_id=i, title=f"Title {i}", cover_color="#6b1a1a"),
            hook=f"Hook {i}.",
        )
        for i in range(1, n + 1)
    ]
    return post(items=items)


def test_renders_cover_items_and_end_slide_at_tiktok_size(tmp_path):
    p = _post(3)
    covers = {i: cover_file(tmp_path / "covers", i) for i in (1, 2, 3)}
    paths = PillowRenderer().render(p, covers, tmp_path / "out")
    assert [x.name for x in paths] == ["01.png", "02.png", "03.png", "04.png", "05.png"]
    for x in paths:
        with Image.open(x) as img:
            assert img.size == (1080, 1920)
            assert img.mode == "RGB"


def test_rerender_removes_stale_slides(tmp_path):
    out = tmp_path / "out"
    covers = {i: cover_file(tmp_path / "covers", i) for i in (1, 2, 3)}
    PillowRenderer().render(_post(3), covers, out)
    PillowRenderer().render(_post(1), covers, out)
    assert sorted(x.name for x in out.glob("*.png")) == ["01.png", "02.png", "03.png"]


def test_missing_or_broken_cover_still_renders(tmp_path):
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    paths = PillowRenderer().render(_post(2), {1: None, 2: broken}, tmp_path / "out")
    assert len(paths) == 4


def test_single_item_post(tmp_path):
    paths = PillowRenderer().render(_post(1), {1: cover_file(tmp_path, 1)}, tmp_path / "out")
    assert len(paths) == 3


def test_manhwa_slide_uses_readable_accent_for_rank(tmp_path):
    """#6b1a1a is too dark; the rank number must be drawn in a lightened red, not the raw colour."""
    PillowRenderer().render(
        _post(1), {1: cover_file(tmp_path, 1, color=(20, 20, 20))}, tmp_path / "out"
    )
    with Image.open(tmp_path / "out" / "02.png") as img:
        colors = {c for _, c in img.getcolors(maxcolors=1 << 20)}
    assert (0x6B, 0x1A, 0x1A) not in colors
    assert hex_to_rgb(readable_accent("#6b1a1a")) in colors
```

- [ ] **Step 3: Run to see it fail**

Run: `uv run pytest tests/unit/test_pillow_renderer.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.adapters.pillow_renderer'`.

- [ ] **Step 4: Implement** — `src/manhwatok/adapters/pillow_renderer.py`:

```python
"""Draws post slides (style C, blur-fill) as 1080×1920 PNGs with Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

from manhwatok.adapters.layout import (
    BAR_H,
    PILL_BORDER,
    PILL_PAD_X,
    SLIDE_H,
    SLIDE_W,
    Pill,
    Placed,
    fit_inside,
    layout_cover,
    layout_end,
    layout_item,
)
from manhwatok.domain.color import hex_to_rgb, readable_accent
from manhwatok.domain.labels import chapter_label
from manhwatok.domain.post import ListPost

WHITE = (255, 255, 255)
DARK = (11, 11, 16)
DIM = (255, 255, 255, 77)
SIZE = (SLIDE_W, SLIDE_H)
GRADIENT_H = 920


def _load(path: Path | None) -> Image.Image | None:
    if path is None:
        return None
    try:
        with Image.open(path) as img:
            return img.convert("RGB")
    except (OSError, UnidentifiedImageError):
        return None


def _blurred(
    img: Image.Image, size: tuple[int, int], radius: float, brightness: float
) -> Image.Image:
    # blur at quarter size then scale up: same look, ~16x faster than blurring full size
    small = ImageOps.fit(img, (size[0] // 4, size[1] // 4), Image.Resampling.LANCZOS)
    small = small.filter(ImageFilter.GaussianBlur(radius / 4))
    small = ImageEnhance.Brightness(small).enhance(brightness)
    return small.resize(size, Image.Resampling.BICUBIC)


def _accent_gradient(size: tuple[int, int], accent: str) -> Image.Image:
    """Stand-in for a missing cover: accent colour fading to near-black."""
    r, g, b = hex_to_rgb(accent)
    column = Image.new("RGB", (1, 256))
    column.putdata(
        [
            (
                int(r * (1 - t / 255) * 0.6),
                int(g * (1 - t / 255) * 0.6),
                int(b * (1 - t / 255) * 0.6),
            )
            for t in range(256)
        ]
    )
    return column.resize(size, Image.Resampling.BICUBIC)


def _bottom_gradient(canvas: Image.Image) -> None:
    """Darken the lowest GRADIENT_H px: transparent → 88% black at 55% → black."""
    alpha = []
    for y in range(GRADIENT_H):
        t = y / (GRADIENT_H - 1)
        a = 0.88 * t / 0.55 if t <= 0.55 else 0.88 + 0.12 * (t - 0.55) / 0.45
        alpha.append(round(255 * a))
    mask = Image.new("L", (1, GRADIENT_H))
    mask.putdata(alpha)
    mask = mask.resize((SLIDE_W, GRADIENT_H))
    canvas.paste((0, 0, 0), (0, SLIDE_H - GRADIENT_H, SLIDE_W, SLIDE_H), mask)


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def _paste_with_shadow(canvas: Image.Image, card: Image.Image, x: int, y: int) -> None:
    """Paste an RGBA card with a soft drop shadow below it."""
    pad = 60
    shadow = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 170), (pad, pad), card.getchannel("A"))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    canvas.alpha_composite(shadow, (x - pad, y - pad + 14))
    canvas.alpha_composite(card, (x, y))


def _draw_text(draw: ImageDraw.ImageDraw, placed: Placed, color, accent) -> None:
    text = placed.text
    for i, base in enumerate(text.baselines(placed.y)):
        x = placed.line_x(i)
        for j, (word, is_accent) in enumerate(text.lines[i]):
            chunk = word if j == len(text.lines[i]) - 1 else word + " "
            draw.text(
                (x, base), chunk, font=text.font, fill=accent if is_accent else color, anchor="ls"
            )
            x += text.font.getlength(chunk)


def _draw_pill(draw: ImageDraw.ImageDraw, pill: Pill, accent, filled: bool) -> None:
    b = pill.box
    rect = (b.x, b.y, b.right, b.bottom)
    if filled:
        draw.rounded_rectangle(rect, radius=b.h // 2, fill=accent)
        color = DARK
    else:
        draw.rounded_rectangle(rect, radius=b.h // 2, outline=accent, width=PILL_BORDER)
        color = accent
    baseline = pill.text_top - pill.text.ink_top
    draw.text(
        (b.x + PILL_PAD_X, baseline),
        pill.text.line_text(0),
        font=pill.text.font,
        fill=color,
        anchor="ls",
    )


class PillowRenderer:
    def render(self, post: ListPost, covers: dict[int, Path | None], out_dir: Path) -> list[Path]:
        """Write 01.png (cover) … NN.png (end slide) into out_dir, replacing old slides."""
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("[0-9][0-9].png"):
            old.unlink()
        images = {m_id: _load(path) for m_id, path in covers.items()}
        slides = [self.cover_slide(post, images)]
        slides += [self.item_slide(post, i, images) for i in range(len(post.items))]
        slides.append(self.end_slide(post, images))
        paths = []
        for n, slide in enumerate(slides, 1):
            path = out_dir / f"{n:02d}.png"
            slide.convert("RGB").save(path)
            paths.append(path)
        return paths

    def item_slide(
        self, post: ListPost, index: int, images: dict[int, Image.Image | None]
    ) -> Image.Image:
        item = post.items[index]
        m = item.manhwa
        accent = hex_to_rgb(readable_accent(m.cover_color, post.accent))
        img = images.get(m.anilist_id)
        canvas = (
            _blurred(img, SIZE, 36, 0.42)
            if img
            else _accent_gradient(SIZE, readable_accent(m.cover_color, post.accent))
        ).convert("RGBA")
        layout = layout_item(index + 1, m.title, chapter_label(m), item.hook)
        src = img or _accent_gradient((460, 650), readable_accent(m.cover_color, post.accent))
        box = fit_inside(src.width, src.height, layout.cover_area)
        card = _rounded(src.resize((box.w, box.h), Image.Resampling.LANCZOS), 24)
        _paste_with_shadow(canvas, card, box.x, box.y)
        _bottom_gradient(canvas)
        draw = ImageDraw.Draw(canvas)
        _draw_text(draw, layout.rank, accent, accent)
        _draw_text(draw, layout.name, WHITE, accent)
        _draw_pill(draw, layout.pill, accent, filled=False)
        if layout.hook:
            _draw_text(draw, layout.hook, WHITE, accent)
        return canvas

    def cover_slide(self, post: ListPost, images: dict[int, Image.Image | None]) -> Image.Image:
        accent = hex_to_rgb(readable_accent(post.accent))
        first = post.items[0].manhwa
        img = images.get(first.anilist_id)
        canvas = (
            _blurred(img, SIZE, 36, 0.42) if img else _accent_gradient(SIZE, post.accent)
        ).convert("RGBA")
        fan = post.items[:3]
        # (item index, size, rotation, centre x, top y); drawn back to front so the centre card is on top
        slots = {
            0: ((440, 624), 0, SLIDE_W // 2, 312),
            1: ((416, 588), 11, SLIDE_W // 2 - 250, 384),
            2: ((416, 588), -11, SLIDE_W // 2 + 250, 384),
        }
        for i in [i for i in (1, 2, 0) if i < len(fan)]:
            size, angle, cx, top = slots[i]
            m = fan[i].manhwa
            src = images.get(m.anilist_id) or _accent_gradient(
                (460, 650), readable_accent(m.cover_color, post.accent)
            )
            card = _rounded(ImageOps.fit(src, size, Image.Resampling.LANCZOS), 20)
            rotated = card.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
            _paste_with_shadow(
                canvas, rotated, cx - rotated.width // 2, top - (rotated.height - size[1]) // 2
            )
        _bottom_gradient(canvas)
        layout = layout_cover(post.title, len(post.items))
        draw = ImageDraw.Draw(canvas)
        _draw_pill(draw, layout.kicker, accent, filled=True)
        _draw_text(draw, layout.title, WHITE, accent)
        for i, seg in enumerate(layout.bar):
            draw.rounded_rectangle(
                (seg.x, seg.y, seg.right, seg.bottom),
                radius=BAR_H // 2,
                fill=accent if i == 0 else DIM,
            )
        return canvas

    def end_slide(self, post: ListPost, images: dict[int, Image.Image | None]) -> Image.Image:
        accent = hex_to_rgb(readable_accent(post.accent))
        canvas = Image.new("RGBA", SIZE, (0, 0, 0, 255))
        tiles = [images.get(it.manhwa.anilist_id) for it in post.items[:4]]
        tiles = [t for t in tiles if t is not None]
        if tiles:
            half = (SLIDE_W // 2, SLIDE_H // 2)
            for k in range(4):
                tile = _blurred(tiles[k % len(tiles)], half, 30, 0.30)
                canvas.paste(tile, ((k % 2) * half[0], (k // 2) * half[1]))
        layout = layout_end([it.manhwa.title for it in post.items])
        draw = ImageDraw.Draw(canvas)
        _draw_text(draw, layout.title, WHITE, accent)
        for i, row in enumerate(layout.rows):
            if row.number:
                item = post.items[i].manhwa
                num_color = hex_to_rgb(readable_accent(item.cover_color, post.accent))
                _draw_text(draw, row.number, num_color, num_color)
            _draw_text(draw, row.name, WHITE, accent)
        _draw_text(draw, layout.follow, WHITE, accent)
        return canvas
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Look at one slide.** Render something real enough to eyeball (optional but recommended — the tests can't judge looks):
```bash
uv run python -c "
from pathlib import Path
from manhwatok.adapters.pillow_renderer import PillowRenderer
from tests.unit.fakes import cover_file, post
out = Path('/tmp/manhwatok-preview'); covers = {i: cover_file(out / 'c', i) for i in (1, 2, 3)}
print(PillowRenderer().render(post(), covers, out))"
```
Expected: five PNGs in `/tmp/manhwatok-preview`; mention in your report that you opened `01.png` and `02.png` and the text is inside the frame.

- [ ] **Step 7: Commit** — `feat: render cover, manhwa and end slides with Pillow`

---

### Task 10: Render and export use cases

**Files:**
- Create: `src/manhwatok/app/post_tools.py`, `src/manhwatok/app/render_post.py`, `src/manhwatok/app/export_post.py`
- Modify: `tests/unit/fakes.py` (add `FakeCovers`, `FakeRenderer`, `ScriptedEditor`, `make_tools`)
- Test: `tests/unit/test_render_export.py`

**Interfaces:**
- Consumes: ports (Task 5), `FsPostRepository` (Task 5), `build_caption` (Task 3), `DraftError`/`NotRendered`/`PostNotFound` (Task 4), `MetadataError`, `PillowRenderer` and `cover_file` (Task 9).
- Produces:
  - `post_tools.PostTools(posts, covers, renderer, editor, progress=noop)` dataclass; `EditorFn = Callable[[str], str | None]`; `ProgressFn = Callable[[str], None]`.
  - `render_post.render_post(post_id, tools) -> list[Path]` — raises `DraftError` for an unfinished post; fetches covers, stopping downloads after the first `MetadataError` (one progress message, remaining covers `None`); writes slides + `caption.txt` into the post folder. Also `CAPTION_FILE = "caption.txt"`, `unfinished_error(post_id) -> DraftError`.
  - `export_post.export_post(post_id, posts: PostRepository, dest_root: Path) -> Path` — copies `NN.png` + `caption.txt` to `dest_root/<id>/` (removing stale `NN.png` there); raises `NotRendered` if slide count ≠ `post.slide_count` or caption missing; `DraftError` if unfinished.
  - Fakes: `FakeCovers(paths: dict[int, Path] | None, fail: set[int] | None)` with `.calls`; `FakeRenderer()` writing placeholder `NN.png` and recording `.calls`; `ScriptedEditor(respond)` with `.shown`; `make_tools(tmp_path, editor=None, covers=None, renderer=None, messages=None) -> PostTools` (real `FsPostRepository(tmp_path / "posts")`, default covers for ids 1, 2, 3, 11, 22, default editor appends a newline).

- [ ] **Step 1: Extend `tests/unit/fakes.py`.** Add to the imports:
```python
from typing import Callable

from manhwatok.domain.errors import MetadataError
```
and append:

```python
class FakeCovers:
    """Returns pre-made cover files; ids in `fail` raise MetadataError like a failed download."""

    def __init__(self, paths: dict[int, Path] | None = None, fail: set[int] | None = None):
        self.paths = dict(paths or {})
        self.fail = set(fail or ())
        self.calls: list[int] = []

    def get(self, manhwa: Manhwa) -> Path:
        self.calls.append(manhwa.anilist_id)
        if manhwa.anilist_id in self.fail or manhwa.anilist_id not in self.paths:
            raise MetadataError(f"cover download failed for {manhwa.title}: HTTP 500")
        return self.paths[manhwa.anilist_id]


class FakeRenderer:
    """Writes placeholder NN.png files instead of drawing, and records what it was given."""

    def __init__(self):
        self.calls: list[tuple[ListPost, dict[int, Path | None]]] = []

    def render(self, post: ListPost, covers: dict[int, Path | None], out_dir: Path) -> list[Path]:
        self.calls.append((post, covers))
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("[0-9][0-9].png"):
            old.unlink()
        paths = [out_dir / f"{n:02d}.png" for n in range(1, post.slide_count + 1)]
        for p in paths:
            p.write_bytes(b"png")
        return paths


class ScriptedEditor:
    """Stands in for $EDITOR: `edit(text)` returns `respond(text)` and remembers what it was shown."""

    def __init__(self, respond: Callable[[str], str | None]):
        self.respond = respond
        self.shown: list[str] = []

    def __call__(self, text: str) -> str | None:
        self.shown.append(text)
        return self.respond(text)


def make_tools(tmp_path: Path, editor=None, covers=None, renderer=None, messages=None):
    """PostTools with real post folders under tmp_path and fakes for everything else."""
    from manhwatok.adapters.fs_posts import FsPostRepository
    from manhwatok.app.post_tools import PostTools

    return PostTools(
        posts=FsPostRepository(tmp_path / "posts"),
        covers=covers or FakeCovers({i: tmp_path / f"{i}.jpg" for i in (1, 2, 3, 11, 22)}),
        renderer=renderer or FakeRenderer(),
        editor=editor or ScriptedEditor(lambda text: text + "\n"),
        progress=(messages.append if messages is not None else lambda _: None),
    )
```

- [ ] **Step 2: Write the failing test** — `tests/unit/test_render_export.py`:

```python
import pytest

from manhwatok.adapters.pillow_renderer import PillowRenderer
from manhwatok.app.export_post import export_post
from manhwatok.app.render_post import render_post
from manhwatok.domain.errors import DraftError, NotRendered, PostNotFound
from tests.unit.fakes import FakeCovers, cover_file, make_tools, post


# --- render ------------------------------------------------------------------------------


def test_render_writes_slides_and_caption(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    slides = render_post("20260914-a3f9", tools)
    folder = tools.posts.folder("20260914-a3f9")
    assert [s.name for s in slides] == ["01.png", "02.png", "03.png", "04.png", "05.png"]
    assert (
        (folder / "caption.txt")
        .read_text()
        .startswith("Manhwa where the MC regresses\n\n1. Title 1")
    )
    _, covers = tools.renderer.calls[0]
    assert covers == {1: tmp_path / "1.jpg", 2: tmp_path / "2.jpg", 3: tmp_path / "3.jpg"}


def test_render_stops_downloading_after_first_cover_failure(tmp_path):
    messages = []
    covers = FakeCovers({1: tmp_path / "1.jpg", 3: tmp_path / "3.jpg"}, fail={2})
    tools = make_tools(tmp_path, covers=covers, messages=messages)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed == {1: tmp_path / "1.jpg", 2: None, 3: None}
    assert covers.calls == [1, 2]
    assert len(messages) == 1
    assert "plain backgrounds" in messages[0]


def test_render_unfinished_post(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(items=[]))
    with pytest.raises(DraftError, match="fix with: manhwatok edit 20260914-a3f9"):
        render_post("20260914-a3f9", tools)


def test_render_unknown_post(tmp_path):
    with pytest.raises(PostNotFound):
        render_post("20260914-ffff", make_tools(tmp_path))


def test_render_with_real_renderer(tmp_path):
    covers = FakeCovers({i: cover_file(tmp_path / "covers", i) for i in (1, 2, 3)})
    tools = make_tools(tmp_path, covers=covers, renderer=PillowRenderer())
    tools.posts.save(post())
    assert len(render_post("20260914-a3f9", tools)) == 5


# --- export ------------------------------------------------------------------------------


def test_export_copies_slides_and_caption(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    dest = export_post("20260914-a3f9", tools.posts, tmp_path / "exports")
    assert dest == tmp_path / "exports" / "20260914-a3f9"
    assert sorted(f.name for f in dest.iterdir()) == [
        "01.png",
        "02.png",
        "03.png",
        "04.png",
        "05.png",
        "caption.txt",
    ]


def test_export_replaces_stale_slides_in_destination(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    stale = tmp_path / "exports" / "20260914-a3f9"
    stale.mkdir(parents=True)
    (stale / "09.png").write_bytes(b"old")
    export_post("20260914-a3f9", tools.posts, tmp_path / "exports")
    assert not (stale / "09.png").exists()


def test_export_before_render(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    with pytest.raises(NotRendered, match="run: manhwatok render 20260914-a3f9"):
        export_post("20260914-a3f9", tools.posts, tmp_path / "exports")


def test_export_unfinished_post(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(items=[]))
    with pytest.raises(DraftError):
        export_post("20260914-a3f9", tools.posts, tmp_path / "exports")
```

- [ ] **Step 3: Run to see it fail**

Run: `uv run pytest tests/unit/test_render_export.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.app.post_tools'`.

- [ ] **Step 4: Implement**

`src/manhwatok/app/post_tools.py`:

```python
"""The collaborators every post use case needs, bundled so commands can pass one object."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from manhwatok.ports.posts import CoverSource, PostRepository, SlideRenderer

# Opens text for editing; returns the edited text, or None if the user aborted or changed nothing
# (click.edit's contract).
EditorFn = Callable[[str], str | None]
ProgressFn = Callable[[str], None]


def _noop(_: str) -> None:
    pass


@dataclass
class PostTools:
    posts: PostRepository
    covers: CoverSource
    renderer: SlideRenderer
    editor: EditorFn
    progress: ProgressFn = _noop
```

`src/manhwatok/app/render_post.py`:

```python
"""Render a saved post's slides and caption into its folder."""

from __future__ import annotations

from pathlib import Path

from manhwatok.app.post_tools import PostTools
from manhwatok.domain.caption import build_caption
from manhwatok.domain.errors import DraftError, MetadataError
from manhwatok.domain.post import ListPost

CAPTION_FILE = "caption.txt"


def unfinished_error(post_id: str) -> DraftError:
    return DraftError(f"post {post_id} has no items — fix with: manhwatok edit {post_id}")


def _cover_paths(post: ListPost, tools: PostTools) -> dict[int, Path | None]:
    """Fetch covers; after the first failure stop downloading so a dead CDN can't stall the run."""
    paths: dict[int, Path | None] = {}
    failed = False
    for item in post.items:
        m = item.manhwa
        paths[m.anilist_id] = None
        if failed:
            continue
        try:
            paths[m.anilist_id] = tools.covers.get(m)
        except MetadataError as e:
            failed = True
            tools.progress(f"{e} — using plain backgrounds for the remaining covers")
    return paths


def render_post(post_id: str, tools: PostTools) -> list[Path]:
    post = tools.posts.get(post_id)
    if post.is_unfinished:
        raise unfinished_error(post_id)
    folder = tools.posts.folder(post_id)
    slides = tools.renderer.render(post, _cover_paths(post, tools), folder)
    (folder / CAPTION_FILE).write_text(build_caption(post) + "\n", encoding="utf-8")
    return slides
```

`src/manhwatok/app/export_post.py`:

```python
"""Copy a rendered post's slides and caption somewhere convenient for uploading."""

from __future__ import annotations

import shutil
from pathlib import Path

from manhwatok.app.render_post import CAPTION_FILE, unfinished_error
from manhwatok.domain.errors import NotRendered
from manhwatok.ports.posts import PostRepository


def export_post(post_id: str, posts: PostRepository, dest_root: Path) -> Path:
    post = posts.get(post_id)
    if post.is_unfinished:
        raise unfinished_error(post_id)
    folder = posts.folder(post_id)
    slides = sorted(folder.glob("[0-9][0-9].png"))
    caption = folder / CAPTION_FILE
    if len(slides) != post.slide_count or not caption.is_file():
        raise NotRendered(
            f"post {post_id} has no up-to-date slides — run: manhwatok render {post_id}"
        )
    dest = dest_root / post_id
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("[0-9][0-9].png"):
        old.unlink()
    for f in [*slides, caption]:
        shutil.copy2(f, dest / f.name)
    return dest
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit** — `feat: render and export use cases`

---

### Task 11: Build and edit use cases

**Files:**
- Create: `src/manhwatok/app/build_post.py`, `src/manhwatok/app/edit_post.py`
- Test: `tests/unit/test_build_edit.py`

**Interfaces:**
- Consumes: `suggest_titles` (Phase 1), `render_draft`/`parse_draft` (Task 4), `first_sentence`/`is_hex_color` (Task 3), `PostTools`/`render_post` (Task 10), fakes incl. `make_tools`.
- Produces:
  - `build_post(query, title, hashtags, accent, metadata, chapters, tools, now: datetime) -> tuple[ListPost, list[Path]] | None` — validates accent (`ManhwatokError("accent must look like #43c9e4, got ...")`) before searching; `ManhwatokError("no matches …")` if the search is empty; prefills hooks with `first_sentence`; `None` if the editor returns `None` (nothing saved); on `DraftError` saves an unfinished post (candidates, no items) plus `draft.txt` and re-raises with `— your draft is saved; fix with: manhwatok edit <id>`; otherwise saves and renders. Post id uses `now.astimezone().date()`; accent stored lowercased.
  - `edit_post(post_id, tools) -> list[Path] | None` — opens the saved `draft.txt` if any, else `render_draft` of the post; `None` if unchanged; on `DraftError` saves the text to `draft.txt` and re-raises with `— your draft is saved; run \`manhwatok edit <id>\` again`; on success saves, clears `draft.txt`, re-renders.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_build_edit.py`:

```python
from datetime import datetime, timezone

import pytest

from manhwatok.app.build_post import build_post
from manhwatok.app.edit_post import edit_post
from manhwatok.domain.errors import DraftError, ManhwatokError
from manhwatok.domain.models import SearchQuery
from tests.unit.fakes import FakeCovers, FakeMetadata, ScriptedEditor, make_tools, manhwa, post

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
Q = SearchQuery(tags=["Revenge"])
CANDIDATES = [
    manhwa(anilist_id=11, title="Doom Breaker", description="Sent back ten years. More."),
    manhwa(anilist_id=22, title="Kubera", description="Gods and more gods. More."),
]


# --- build -------------------------------------------------------------------------------


def _build(tools, title="MC *regresses*", accent="#43C9E4", results=CANDIDATES):
    return build_post(Q, title, "#manhwa", accent, FakeMetadata(results), None, tools, now=NOW)


def test_build_prefills_draft_saves_and_renders(tmp_path):
    editor = ScriptedEditor(lambda text: text.replace("Sent back ten years.", "Ten years back!"))
    tools = make_tools(tmp_path, editor=editor)
    built, slides = _build(tools)
    shown = editor.shown[0]
    assert "title: MC *regresses*" in shown
    assert "11 | Doom Breaker | Sent back ten years." in shown
    assert "22 | Kubera | Gods and more gods." in shown
    assert built.title == "MC *regresses*"
    assert [(i.manhwa.anilist_id, i.hook) for i in built.items] == [
        (11, "Ten years back!"),
        (22, "Gods and more gods."),
    ]
    assert built.accent == "#43c9e4"
    assert built.hashtags == "#manhwa"
    assert built.created_at == NOW
    assert built.id.startswith(NOW.astimezone().strftime("%Y%m%d") + "-")
    assert tools.posts.get(built.id) == built
    assert len(slides) == 4


def test_build_cancelled_saves_nothing(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: None))
    assert _build(tools) is None
    assert tools.posts.list() == []


def test_build_bad_draft_keeps_text_for_edit(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: "title: T\n999 | nope | x\n"))
    with pytest.raises(
        DraftError, match=r"999 is not one of .* fix with: manhwatok edit \d{8}-[0-9a-f]{4}"
    ):
        _build(tools)
    [saved] = tools.posts.list()
    assert saved.is_unfinished
    assert saved.candidates == CANDIDATES
    assert tools.posts.load_draft(saved.id) == "title: T\n999 | nope | x\n"
    assert tools.renderer.calls == []


def test_build_no_matches(tmp_path):
    with pytest.raises(ManhwatokError, match="no matches"):
        _build(make_tools(tmp_path), results=[])


def test_build_rejects_bad_accent_before_searching(tmp_path):
    editor = ScriptedEditor(lambda text: text)
    with pytest.raises(ManhwatokError, match="accent must look like #43c9e4"):
        _build(make_tools(tmp_path, editor=editor), accent="cyan")
    assert editor.shown == []


# --- edit --------------------------------------------------------------------------------


def test_edit_reopens_current_post_and_rerenders(tmp_path):
    editor = ScriptedEditor(lambda text: text.replace("Hook 2", "Better hook"))
    tools = make_tools(tmp_path, editor=editor)
    tools.posts.save(post())
    slides = edit_post("20260914-a3f9", tools)
    assert "2 | Title 2 | Hook 2" in editor.shown[0]
    assert tools.posts.get("20260914-a3f9").items[1].hook == "Better hook"
    assert len(slides) == 5


def test_edit_resumes_saved_broken_draft_and_clears_it(tmp_path):
    editor = ScriptedEditor(lambda text: "title: Fixed\n1 | Title 1 | ok\n")
    tools = make_tools(tmp_path, editor=editor)
    tools.posts.save(post(items=[], candidates=[manhwa(anilist_id=1, title="Title 1")]))
    tools.posts.save_draft("20260914-a3f9", "title: T\n999 | nope | x\n")
    edit_post("20260914-a3f9", tools)
    assert editor.shown[0] == "title: T\n999 | nope | x\n"
    assert tools.posts.load_draft("20260914-a3f9") is None
    assert tools.posts.get("20260914-a3f9").title == "Fixed"


def test_edit_can_bring_back_a_dropped_candidate(tmp_path):
    def restore(text):
        return text.replace("# 9 | Dropped | ", "9 | Dropped | ")

    extra = manhwa(anilist_id=9, title="Dropped", description="Was cut. More.")
    tools = make_tools(tmp_path, editor=ScriptedEditor(restore), covers=FakeCovers({}))
    p = post()
    tools.posts.save(p.model_copy(update={"candidates": p.candidates + [extra]}))
    edit_post("20260914-a3f9", tools)
    assert [i.manhwa.anilist_id for i in tools.posts.get("20260914-a3f9").items] == [1, 2, 3, 9]


def test_edit_no_changes(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: None))
    tools.posts.save(post())
    assert edit_post("20260914-a3f9", tools) is None
    assert tools.renderer.calls == []


def test_edit_bad_draft_is_saved(tmp_path):
    tools = make_tools(tmp_path, editor=ScriptedEditor(lambda text: "title: T\n"))
    tools.posts.save(post())
    with pytest.raises(DraftError, match="run `manhwatok edit 20260914-a3f9` again"):
        edit_post("20260914-a3f9", tools)
    assert tools.posts.load_draft("20260914-a3f9") == "title: T\n"
    assert tools.posts.get("20260914-a3f9") == post()
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_build_edit.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'manhwatok.app.build_post'`.

- [ ] **Step 3: Implement**

`src/manhwatok/app/build_post.py`:

```python
"""Theme → candidates → draft in the editor → saved, rendered post."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_post
from manhwatok.app.suggest import suggest_titles
from manhwatok.domain.color import is_hex_color
from manhwatok.domain.draft import parse_draft, render_draft
from manhwatok.domain.errors import DraftError, ManhwatokError
from manhwatok.domain.models import SearchQuery
from manhwatok.domain.post import ListPost, PostItem
from manhwatok.domain.text import first_sentence
from manhwatok.ports.metadata import ChapterSource, MetadataSource


def build_post(
    query: SearchQuery,
    title: str,
    hashtags: str,
    accent: str,
    metadata: MetadataSource,
    chapters: ChapterSource | None,
    tools: PostTools,
    now: datetime,
) -> tuple[ListPost, list[Path]] | None:
    """Returns (post, slide paths), or None if the user closed the editor without changes."""
    if not is_hex_color(accent):
        raise ManhwatokError(f"accent must look like #43c9e4, got {accent!r}")
    candidates = suggest_titles(query, metadata, chapters, progress=tools.progress)
    if not candidates:
        raise ManhwatokError("no matches — try fewer tags or a lower --min-tag-rank")
    items = [PostItem(manhwa=m, hook=first_sentence(m.description)) for m in candidates]
    edited = tools.editor(render_draft(title, items, candidates))
    if edited is None:
        return None

    post = ListPost(
        id=tools.posts.new_id(now.astimezone().date()),
        created_at=now,
        candidates=candidates,
        hashtags=hashtags,
        accent=accent.lower(),
    )
    try:
        title, items = parse_draft(edited, candidates)
    except DraftError as e:
        tools.posts.save(post)
        tools.posts.save_draft(post.id, edited)
        raise DraftError(f"{e} — your draft is saved; fix with: manhwatok edit {post.id}") from e
    post = post.model_copy(update={"title": title, "items": items})
    tools.posts.save(post)
    return post, render_post(post.id, tools)
```

`src/manhwatok/app/edit_post.py`:

```python
"""Reopen a post's draft in the editor, save the result and re-render."""

from __future__ import annotations

from pathlib import Path

from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_post
from manhwatok.domain.draft import parse_draft, render_draft
from manhwatok.domain.errors import DraftError


def edit_post(post_id: str, tools: PostTools) -> list[Path] | None:
    """Returns the new slide paths, or None if the user closed the editor without changes."""
    post = tools.posts.get(post_id)
    text = tools.posts.load_draft(post_id) or render_draft(post.title, post.items, post.candidates)
    edited = tools.editor(text)
    if edited is None:
        return None
    try:
        title, items = parse_draft(edited, post.candidates)
    except DraftError as e:
        tools.posts.save_draft(post_id, edited)
        raise DraftError(f"{e} — your draft is saved; run `manhwatok edit {post_id}` again") from e
    tools.posts.save(post.model_copy(update={"title": title, "items": items}))
    tools.posts.clear_draft(post_id)
    return render_post(post_id, tools)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `feat: build and edit posts through a draft file`

---

### Task 12: CLI commands and wiring

**Files:**
- Modify: `src/manhwatok/app/container.py` (replace whole file), `src/manhwatok/cli.py` (replace whole file)
- Test: `tests/unit/test_cli_posts.py`, `tests/unit/test_container.py` (append)

**Interfaces:**
- Consumes: all use cases (Tasks 10–11), `edit_text` (Task 7), `FsPostRepository`, `CoverCache`, `PillowRenderer`, `Settings` paths (Task 5).
- Produces: `container.build_post_tools(settings, editor: EditorFn, progress: ProgressFn) -> PostTools`; commands `build`, `edit`, `render`, `export`, `posts`. The search options (`-t/-g/--sort/-n/--min-tag-rank/--chapters`) are module-level `typer.Option` constants shared by `suggest` and `build`, validated by `_query()`; `suggest`'s behaviour and output are unchanged (Phase 1 tests must keep passing). Commands call `container.build_…` via the module so tests can monkeypatch them.

Command output (tests assert these strings):
- build: `post <id> · <N> slides → <folder>` then `export with: manhwatok export <id>`; cancelled: `cancelled — nothing saved`.
- edit: `post <id> · <N> slides → <folder>`; unchanged: `no changes`.
- render: `post <id> · <N> slides → <folder>`.
- export: `exported → <dest>`.
- posts: `<id>  <YYYY-MM-DD HH:MM local>  <"N slides" | "draft", right-aligned 9>  <plain title | (untitled)>`; none: `no posts yet — try: manhwatok build -t Revenge`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_cli_posts.py`:

```python
import re

import pytest
from typer.testing import CliRunner

from manhwatok.adapters.fs_posts import FsPostRepository
from manhwatok.app import container
from manhwatok.app.post_tools import PostTools
from manhwatok.cli import app
from tests.unit.fakes import (
    FakeChapters,
    FakeCovers,
    FakeMetadata,
    FakeRenderer,
    ScriptedEditor,
    manhwa,
    post,
)

runner = CliRunner()
CANDIDATES = [
    manhwa(anilist_id=11, title="Doom Breaker", description="Sent back ten years. More."),
    manhwa(anilist_id=22, title="Kubera", description="Gods. More."),
]


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MANHWATOK_EXPORT_DIR", str(tmp_path / "exports"))


@pytest.fixture
def wire(tmp_path, monkeypatch):
    """Fake network, editor and renderer; real post folders under tmp_path."""

    def _wire(respond=lambda text: text + "\n", results=CANDIDATES):
        editor = ScriptedEditor(respond)
        repo = FsPostRepository(tmp_path / "data" / "posts")
        monkeypatch.setattr(container, "build_metadata", lambda settings: FakeMetadata(results))
        monkeypatch.setattr(container, "build_chapter_source", lambda settings: FakeChapters({}))
        monkeypatch.setattr(
            container,
            "build_post_tools",
            lambda settings, _editor, progress: PostTools(
                repo,
                FakeCovers({11: tmp_path / "11.jpg", 22: tmp_path / "22.jpg"}),
                FakeRenderer(),
                editor,
                progress,
            ),
        )
        return repo, editor

    return _wire


def _post_id(output: str) -> str:
    return re.search(r"post (\d{8}-[0-9a-f]{4})", output).group(1)


def test_build_renders_and_prints_next_step(wire):
    repo, editor = wire()
    result = runner.invoke(
        app, ["build", "-t", "Revenge", "--title", "MC *regresses*", "--no-chapters"]
    )
    assert result.exit_code == 0, result.output
    post_id = _post_id(result.output)
    assert "· 4 slides →" in result.output
    assert f"export with: manhwatok export {post_id}" in result.output
    assert repo.get(post_id).title == "MC *regresses*"
    assert "title: MC *regresses*" in editor.shown[0]


def test_build_requires_a_filter(wire):
    wire()
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 1
    assert "at least one --tag or --genre" in result.output


def test_build_cancelled(wire):
    repo, _ = wire(respond=lambda text: None)
    result = runner.invoke(app, ["build", "-t", "Revenge"])
    assert result.exit_code == 0
    assert "cancelled — nothing saved" in result.output
    assert repo.list() == []


def test_build_bad_draft_exits_1_with_edit_hint(wire):
    wire(respond=lambda text: "title: T\n")
    result = runner.invoke(app, ["build", "-t", "Revenge"])
    assert result.exit_code == 1
    assert "error: no titles left" in result.output
    assert "fix with: manhwatok edit" in result.output


def test_build_bad_accent(wire):
    wire()
    result = runner.invoke(app, ["build", "-t", "Revenge", "--accent", "cyan"])
    assert result.exit_code == 1
    assert "accent must look like #43c9e4" in result.output


def test_edit_render_export_posts_flow(wire, tmp_path):
    repo, _ = wire(respond=lambda text: text.replace("Hook 1", "New hook"))
    repo.save(post())

    result = runner.invoke(app, ["edit", "20260914-a3f9"])
    assert result.exit_code == 0, result.output
    assert "post 20260914-a3f9 · 5 slides →" in result.output
    assert repo.get("20260914-a3f9").items[0].hook == "New hook"

    result = runner.invoke(app, ["render", "20260914-a3f9"])
    assert result.exit_code == 0, result.output
    assert "5 slides" in result.output

    result = runner.invoke(app, ["export", "20260914-a3f9"])
    assert result.exit_code == 0, result.output
    assert f"exported → {tmp_path / 'exports' / '20260914-a3f9'}" in result.output
    assert (tmp_path / "exports" / "20260914-a3f9" / "caption.txt").is_file()

    result = runner.invoke(app, ["export", "20260914-a3f9", "--out", str(tmp_path / "elsewhere")])
    assert result.exit_code == 0
    assert (tmp_path / "elsewhere" / "20260914-a3f9" / "05.png").is_file()


def test_edit_no_changes(wire):
    repo, _ = wire(respond=lambda text: None)
    repo.save(post())
    result = runner.invoke(app, ["edit", "20260914-a3f9"])
    assert result.exit_code == 0
    assert "no changes" in result.output


@pytest.mark.parametrize("command", ["edit", "render", "export"])
def test_unknown_post(wire, command):
    wire()
    result = runner.invoke(app, [command, "20260914-ffff"])
    assert result.exit_code == 1
    assert "error: no post 20260914-ffff" in result.output


def test_export_before_render(wire):
    repo, _ = wire()
    repo.save(post())
    result = runner.invoke(app, ["export", "20260914-a3f9"])
    assert result.exit_code == 1
    assert "run: manhwatok render 20260914-a3f9" in result.output


def test_posts_lists_newest_first_and_marks_drafts(wire):
    from datetime import datetime, timezone

    repo, _ = wire()
    repo.save(post(id="20260913-0001", created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    repo.save(
        post(
            id="20260914-0002",
            title="",
            items=[],
            created_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )
    )
    result = runner.invoke(app, ["posts"])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert lines[0].startswith("20260914-0002") and "draft" in lines[0] and "(untitled)" in lines[0]
    assert lines[1].startswith("20260913-0001") and "5 slides" in lines[1]
    assert "Manhwa where the MC regresses" in lines[1]


def test_posts_empty(wire):
    wire()
    result = runner.invoke(app, ["posts"])
    assert "no posts yet" in result.output


def test_help_lists_post_commands():
    result = runner.invoke(app, ["--help"])
    for command in ("build", "edit", "render", "export", "posts"):
        assert command in result.output
```

Append to `tests/unit/test_container.py`:

```python
def test_build_post_tools_wires_real_adapters(tmp_path):
    from manhwatok.adapters.cover_cache import CoverCache
    from manhwatok.adapters.fs_posts import FsPostRepository
    from manhwatok.adapters.pillow_renderer import PillowRenderer
    from manhwatok.app.container import build_post_tools

    def editor(text):
        return None

    tools = build_post_tools(Settings(data_dir=tmp_path), editor, print)
    assert isinstance(tools.posts, FsPostRepository)
    assert isinstance(tools.covers, CoverCache)
    assert isinstance(tools.renderer, PillowRenderer)
    assert tools.editor is editor
    assert tools.posts.folder("20260914-a3f9") == tmp_path / "posts" / "20260914-a3f9"
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_cli_posts.py tests/unit/test_container.py -q`
Expected: FAIL — `AttributeError: <module 'manhwatok.app.container'> does not have the attribute 'build_post_tools'` / `No such command 'build'`.

- [ ] **Step 3: Implement**

`src/manhwatok/app/container.py` (whole file):

```python
"""Composition root: builds adapters from settings. Imports adapters lazily so
`--help` stays fast."""

from __future__ import annotations

from manhwatok.app.post_tools import EditorFn, PostTools, ProgressFn
from manhwatok.config import Settings
from manhwatok.ports.metadata import ChapterSource, MetadataSource


def build_metadata(settings: Settings) -> MetadataSource:
    from manhwatok.adapters.anilist import AniListSource

    return AniListSource(timeout=settings.http_timeout)


def build_chapter_source(settings: Settings) -> ChapterSource:
    from manhwatok.adapters.cached_chapters import CachedChapterSource
    from manhwatok.adapters.mangaupdates import MangaUpdatesSource
    from manhwatok.adapters.sqlite_cache import SqliteCache

    return CachedChapterSource(
        MangaUpdatesSource(timeout=settings.http_timeout),
        SqliteCache(settings.db_path),
        max_age=settings.chapter_cache_hours * 3600,
    )


def build_post_tools(settings: Settings, editor: EditorFn, progress: ProgressFn) -> PostTools:
    from manhwatok.adapters.cover_cache import CoverCache
    from manhwatok.adapters.fs_posts import FsPostRepository
    from manhwatok.adapters.pillow_renderer import PillowRenderer

    return PostTools(
        posts=FsPostRepository(settings.posts_dir),
        covers=CoverCache(settings.covers_dir, timeout=settings.http_timeout),
        renderer=PillowRenderer(),
        editor=editor,
        progress=progress,
    )
```

`src/manhwatok/cli.py` (whole file):

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn, Optional

import typer

from manhwatok.config import Settings
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import SearchQuery, Sort
from manhwatok.domain.post import DEFAULT_ACCENT, DEFAULT_HASHTAGS

app = typer.Typer(
    help="Themed manhwa recommendation slideshows for TikTok.", no_args_is_help=True
)


@app.callback()
def main() -> None:
    """Themed manhwa recommendation slideshows for TikTok."""


def _progress(msg: str) -> None:
    typer.secho(f"  {msg}", fg=typer.colors.CYAN, err=True)


def _fail(e: Exception) -> NoReturn:
    typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


# Search options shared by `suggest` and `build`.
TAG = typer.Option(
    None, "--tag", "-t", help="AniList tag; repeat to require several (see `manhwatok tags`)."
)
GENRE = typer.Option(None, "--genre", "-g", help="AniList genre; repeat to require several.")
SORT = typer.Option(Sort.SCORE, help="Ranking order.")
LIMIT = typer.Option(12, "--limit", "-n", min=1, max=50, help="How many titles.")
MIN_TAG_RANK = typer.Option(
    60, min=0, max=100, help="Ignore titles where the tag is weaker than this rank."
)
CHAPTERS = typer.Option(
    True, "--chapters/--no-chapters", help="Look up missing chapter counts on MangaUpdates."
)


def _query(
    tag: Optional[list[str]], genre: Optional[list[str]], sort: Sort, limit: int, min_tag_rank: int
) -> SearchQuery:
    if not tag and not genre:
        _fail(ValueError("give at least one --tag or --genre"))
    return SearchQuery(
        tags=tag or [], genres=genre or [], sort=sort, limit=limit, min_tag_rank=min_tag_rank
    )


@app.command()
def suggest(
    tag: Optional[list[str]] = TAG,
    genre: Optional[list[str]] = GENRE,
    sort: Sort = SORT,
    limit: int = LIMIT,
    min_tag_rank: int = MIN_TAG_RANK,
    chapters: bool = CHAPTERS,
) -> None:
    """Suggest top Korean manhwa matching tags/genres."""
    from manhwatok.app import container
    from manhwatok.app.suggest import suggest_titles
    from manhwatok.domain.labels import chapter_label

    query = _query(tag, genre, sort, limit, min_tag_rank)
    settings = Settings()
    try:
        results = suggest_titles(
            query,
            container.build_metadata(settings),
            container.build_chapter_source(settings) if chapters else None,
            progress=_progress,
        )
    except ManhwatokError as e:
        _fail(e)
    if not results:
        typer.echo("no matches — try fewer tags or a lower --min-tag-rank")
        return
    for i, m in enumerate(results, 1):
        score = f"{m.score}%" if m.score is not None else "–"
        typer.echo(f"{i:>2}. {m.title}  [{chapter_label(m)}]  {score}")
        typer.secho(f"    {', '.join(m.genres)}", dim=True)


@app.command()
def tags(
    search: Optional[str] = typer.Argument(None, help="Match tag name or description."),
    category: Optional[str] = typer.Option(None, help="Category prefix, e.g. 'Theme'."),
) -> None:
    """List AniList tags usable with `suggest --tag`."""
    from manhwatok.app import container

    try:
        items = container.build_metadata(Settings()).list_tags()
    except ManhwatokError as e:
        _fail(e)
    if search:
        s = search.casefold()
        items = [t for t in items if s in t.name.casefold() or s in t.description.casefold()]
    if category:
        c = category.casefold()
        items = [t for t in items if t.category.casefold().startswith(c)]
    current = None
    for t in sorted(items, key=lambda t: (t.category, t.name)):
        if t.category != current:
            typer.secho(t.category, bold=True)
            current = t.category
        typer.echo(f"  {t.name}")


def _tools(settings: Settings):
    from manhwatok.adapters.editor import edit_text
    from manhwatok.app import container

    return container.build_post_tools(settings, edit_text, _progress)


@app.command()
def build(
    tag: Optional[list[str]] = TAG,
    genre: Optional[list[str]] = GENRE,
    sort: Sort = SORT,
    limit: int = LIMIT,
    min_tag_rank: int = MIN_TAG_RANK,
    chapters: bool = CHAPTERS,
    title: str = typer.Option("", help="Post title; wrap words in *stars* to colour them."),
    hashtags: str = typer.Option(DEFAULT_HASHTAGS, help="Hashtags appended to the caption."),
    accent: str = typer.Option(DEFAULT_ACCENT, help="Accent colour for cover and end slides."),
) -> None:
    """Build a post: pick titles and hooks in your editor, then render the slides."""
    from manhwatok.app import container
    from manhwatok.app.build_post import build_post

    query = _query(tag, genre, sort, limit, min_tag_rank)
    settings = Settings()
    try:
        tools = _tools(settings)
        built = build_post(
            query,
            title,
            hashtags,
            accent,
            container.build_metadata(settings),
            container.build_chapter_source(settings) if chapters else None,
            tools,
            now=datetime.now(timezone.utc),
        )
    except ManhwatokError as e:
        _fail(e)
    if built is None:
        typer.echo("cancelled — nothing saved")
        return
    post, slides = built
    typer.echo(f"post {post.id} · {len(slides)} slides → {tools.posts.folder(post.id)}")
    typer.echo(f"export with: manhwatok export {post.id}")


@app.command()
def edit(post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`.")) -> None:
    """Reopen a post's draft in your editor and re-render it."""
    from manhwatok.app.edit_post import edit_post

    settings = Settings()
    try:
        tools = _tools(settings)
        slides = edit_post(post_id, tools)
    except ManhwatokError as e:
        _fail(e)
    if slides is None:
        typer.echo("no changes")
        return
    typer.echo(f"post {post_id} · {len(slides)} slides → {tools.posts.folder(post_id)}")


@app.command()
def render(post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`.")) -> None:
    """Re-render a post's slides and caption."""
    from manhwatok.app.render_post import render_post

    settings = Settings()
    try:
        tools = _tools(settings)
        slides = render_post(post_id, tools)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"post {post_id} · {len(slides)} slides → {tools.posts.folder(post_id)}")


@app.command()
def export(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    out: Optional[Path] = typer.Option(
        None, help="Folder to export into (default: ~/Downloads/manhwatok)."
    ),
) -> None:
    """Copy a post's slides and caption.txt to a folder for uploading."""
    from manhwatok.app.export_post import export_post

    settings = Settings()
    try:
        dest = export_post(post_id, _tools(settings).posts, out or settings.export_dir)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"exported → {dest}")


@app.command()
def posts() -> None:
    """List saved posts, newest first."""
    from manhwatok.domain.text import plain_title

    try:
        saved = _tools(Settings()).posts.list()
    except ManhwatokError as e:
        _fail(e)
    if not saved:
        typer.echo("no posts yet — try: manhwatok build -t Revenge")
        return
    for post in saved:
        when = post.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
        size = "draft" if post.is_unfinished else f"{post.slide_count} slides"
        typer.echo(f"{post.id}  {when}  {size:>9}  {plain_title(post.title) or '(untitled)'}")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass (203 passed, 3 skipped at this point; Phase 1 CLI tests included).

- [ ] **Step 5: Try it by hand (no network needed for help):** `uv run manhwatok --help` lists suggest, tags, build, edit, render, export, posts; `uv run manhwatok posts` prints `no posts yet …` with a temp `MANHWATOK_DATA_DIR`.

- [ ] **Step 6: Commit** — `feat: build, edit, render, export and posts commands`

---

### Task 13: Live end-to-end test and README

**Files:**
- Create: `tests/integration/test_live_build.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: container builders (Task 12), `build_post` (Task 11).

- [ ] **Step 1: Write the live test** — `tests/integration/test_live_build.py`:

```python
"""Build and render a real post from live AniList + covers.

Run with: MANHWATOK_LIVE=1 uv run pytest tests/integration/test_live_build.py -s
The rendered folder is printed so you can look at the PNGs.
"""

import os
from datetime import datetime, timezone

import pytest
from PIL import Image

from manhwatok.app.build_post import build_post
from manhwatok.app.container import build_chapter_source, build_metadata, build_post_tools
from manhwatok.config import Settings
from manhwatok.domain.models import SearchQuery

pytestmark = pytest.mark.skipif(
    os.environ.get("MANHWATOK_LIVE") != "1", reason="set MANHWATOK_LIVE=1 to hit real APIs"
)


def _keep_first_five(text: str) -> str:
    """Scripted 'editor': keep the title and the first five pick lines, comment out the rest."""
    out, kept = [], 0
    for line in text.splitlines():
        if line and not line.startswith(("#", "title:")):
            if kept >= 5:
                line = "# " + line
            kept += 1
        out.append(line)
    return "\n".join(out) + "\n"


def test_build_real_post(tmp_path):
    settings = Settings(data_dir=tmp_path)
    tools = build_post_tools(settings, _keep_first_five, print)
    built = build_post(
        SearchQuery(tags=["Time Manipulation", "Revenge"], limit=8),
        "Manhwa where the MC *regresses* for *revenge*",
        "#manhwa #webtoon",
        "#43c9e4",
        build_metadata(settings),
        build_chapter_source(settings),
        tools,
        now=datetime.now(timezone.utc),
    )
    assert built is not None
    post, slides = built
    assert len(post.items) == 5
    assert len(slides) == 7
    for path in slides:
        with Image.open(path) as img:
            assert img.size == (1080, 1920)
    assert len(list(settings.covers_dir.iterdir())) == 5
    print(f"\nrendered post → {tools.posts.folder(post.id)}")
```

- [ ] **Step 2: Run offline and live**

Run: `uv run pytest -q` → the new test is skipped (4 skipped).
Run: `MANHWATOK_LIVE=1 uv run pytest tests/integration/test_live_build.py -q -s` → 1 passed, prints `rendered post → <folder>`. Open `01.png`, `02.png` and the last slide from that folder and say in your report what you saw (cover fan + title, manhwa slide, recap list).

- [ ] **Step 3: README.** In `README.md`, change the intro line `Phase 1: find the best Korean manhwa for a theme, with chapter counts.` to `Find the best Korean manhwa for a theme, then turn the list into a ready-to-upload TikTok photo carousel.` and insert this section before `## Tests`:

````markdown
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
`$XDG_DATA_HOME/manhwatok/posts/<id>/`.

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
````

- [ ] **Step 4: Commit** — `test: live post build; docs: README for posts`
