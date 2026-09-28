# New Post Kinds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four new post kinds — `similar` (If you liked X), `versus`, `guess`, `characters` — built, rendered, captioned and counted as posted like list posts, reachable from web, CLI and TUI.

**Architecture:** A `PostKind` on `ListPost` (defaulted, validator-derived for chapters) selects the build flow, the middle/end slides (new `adapters/kind_slides.py`, reusing `pillow_renderer` helpers the way `cover_designs.py` does) and the caption. Every non-chapter kind keeps the 7 list covers; only the cover's pill label changes. AniList gains `recommendations` and a batched `characters` lookup.

**Tech Stack:** Python 3.13, pydantic, Pillow, httpx (AniList GraphQL), FastAPI + Jinja + htmx, Textual, Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-post-kinds-design.md`

**Deviation from spec (decided while planning):** character names are not stored on `Manhwa`. Instead `MetadataSource.characters(ids)` returns `CharacterPick`s in the same order and filter as `Manhwa.character_urls` (FAVOURITES_DESC, pictured only), and a pick stores its `index` into that list, so the renderer downloads it with the existing `covers.get_character(manhwa, index)`. At build time the item's `manhwa.character_urls` is refreshed from the lookup so index and picture agree.

## Global Constraints
- Every existing post.json must load unchanged (new fields defaulted).
- Slides per post ≤ 35 (cover + 33 + end): list/similar/characters ≤ 33 items; versus ≤ 33 rounds (66 picks, even count); guess ≤ 16 titles.
- Cover text ends at `COVER_BOTTOM` (1350); item/end text inside `SAFE`.
- History records `items[].manhwa.anilist_id` only (seed excluded).
- Run tests with `uv run pytest`; commit after each task, message ending with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus
1. Versus with an odd number of picks → a clear DraftError, not a crash or a lone half-slide. (Task 1 test)
2. Similar where AniList has no recommendations, or all were posted recently → "no recommendations for X" error, no empty post. (Task 3 test)
3. Characters where a title has no pictured characters → that title is refused by name at save. (Task 6 test)
4. Guess clue must not show the title: a cover with its lettering is the last resort and is cut clear of text. (Task 5 test: custom/gallery preferred over cover)
5. Older posts (no `kind`) open, render and caption exactly as before. (Task 1 test)

---

### Task 1: Model — PostKind, seed, CharacterPick, per-kind rules

**Files:**
- Modify: `src/manhwatok/domain/models.py` (add `PostKind`, `CharacterPick`)
- Modify: `src/manhwatok/domain/post.py` (fields, validator, slide_count, `cover_kicker`)
- Modify: `src/manhwatok/domain/draft.py:78` (`check_picks(title, items, kind=PostKind.LIST)`)
- Test: `tests/unit/test_post_kinds.py`

**Interfaces — Produces:**
- `PostKind(StrEnum)`: `LIST="list"`, `CHAPTER="chapter"`, `SIMILAR="similar"`, `VERSUS="versus"`, `GUESS="guess"`, `CHARACTERS="characters"`.
- `CharacterPick(BaseModel)`: `name: str`, `role: str = ""`, `favourites: int = 0`, `index: int = 0`.
- `PostItem.character: CharacterPick | None = None`; `ListPost.kind: PostKind = LIST`; `ListPost.seed: Manhwa | None = None`.
- `ListPost.slide_count`, `cover_kicker(post) -> str` (in `domain/post.py`).
- `MAX_GUESS = 16`, `check_picks(title, items, kind)`.

- [ ] **Step 1: failing tests** (`tests/unit/test_post_kinds.py`)

```python
import pytest

from manhwatok.domain.draft import check_picks
from manhwatok.domain.errors import DraftError
from manhwatok.domain.models import CharacterPick, PostKind
from manhwatok.domain.post import MAX_GUESS, PostItem, cover_kicker
from tests.unit.fakes import chapter_part, chapter_post, manhwa, post


def _items(n, character=False):
    return [
        PostItem(
            manhwa=manhwa(anilist_id=i, title=f"T{i}"),
            character=CharacterPick(name=f"C{i}") if character else None,
        )
        for i in range(1, n + 1)
    ]


def test_old_posts_load_as_list_and_chapter():
    assert post().kind is PostKind.LIST
    data = chapter_post(chapter=chapter_part()).model_dump(mode="json")
    del data["kind"]
    assert type(post()).model_validate(data).kind is PostKind.CHAPTER


@pytest.mark.parametrize(
    ("kind", "n", "slides"),
    [(PostKind.LIST, 5, 7), (PostKind.SIMILAR, 5, 7), (PostKind.VERSUS, 6, 5),
     (PostKind.GUESS, 4, 10), (PostKind.CHARACTERS, 3, 5)],
)
def test_slide_count_by_kind(kind, n, slides):
    assert post(items=_items(n, True), kind=kind).slide_count == slides


@pytest.mark.parametrize(
    ("kind", "n", "label"),
    [(PostKind.LIST, 5, "5 PICKS"), (PostKind.LIST, 1, "1 PICK"), (PostKind.SIMILAR, 5, "IF YOU LIKED"),
     (PostKind.VERSUS, 6, "3 ROUNDS"), (PostKind.GUESS, 4, "GUESS 4"), (PostKind.CHARACTERS, 3, "TOP 3")],
)
def test_cover_kicker_by_kind(kind, n, label):
    assert cover_kicker(post(items=_items(n, True), kind=kind)) == label


def test_versus_needs_an_even_count():
    with pytest.raises(DraftError, match="pairs"):
        check_picks("T", _items(3), PostKind.VERSUS)
    check_picks("T", _items(4), PostKind.VERSUS)


def test_guess_is_capped():
    with pytest.raises(DraftError, match=str(MAX_GUESS)):
        check_picks("T", _items(MAX_GUESS + 1), PostKind.GUESS)


def test_characters_need_a_character_each():
    with pytest.raises(DraftError, match="T2"):
        check_picks("T", _items(1, True) + [_items(2)[1]], PostKind.CHARACTERS)
```

- [ ] **Step 2:** `uv run pytest tests/unit/test_post_kinds.py -q` → FAIL (ImportError).

- [ ] **Step 3: implement.** In `models.py` after `ChapterCoverStyle`:

```python
class PostKind(StrEnum):
    """What a post's slides are about. A list post ranks titles; the others reshape that."""

    LIST = "list"  # a recommendation list: one slide per title
    CHAPTER = "chapter"  # part of a chapter: one slide per panel
    SIMILAR = "similar"  # "if you liked X": X's AniList recommendations as a list
    VERSUS = "versus"  # titles in pairs, one slide per pair, viewers vote
    GUESS = "guess"  # per title a clue slide, then its reveal
    CHARACTERS = "characters"  # a ranking of characters, one per title


class CharacterPick(BaseModel):
    """One of a title's characters, as a characters post ranks it. `index` is its place in
    the title's `characters` (pictured, most favourited first), where its picture is fetched."""

    name: str
    role: str = ""  # AniList's MAIN / SUPPORTING / BACKGROUND
    favourites: int = 0
    index: int = 0
```

In `post.py`: import `PostKind, CharacterPick`, `model_validator`; add `character: CharacterPick | None = None` to `PostItem`; add to `ListPost`:

```python
    kind: PostKind = PostKind.LIST
    seed: Manhwa | None = None  # a similar post's "if you liked" title; never one of its items

    @model_validator(mode="after")
    def _chapter_kind(self) -> "ListPost":
        # Chapter posts saved before `kind` existed say so only by carrying a chapter.
        if self.chapter is not None and self.kind is not PostKind.CHAPTER:
            object.__setattr__(self, "kind", PostKind.CHAPTER)
        return self
```

Replace `slide_count`:

```python
    @property
    def slide_count(self) -> int:
        if self.chapter:
            return len(self.chapter.panels) + 2
        n = len(self.items)
        if self.kind is PostKind.VERSUS:
            return (n + 1) // 2 + 2
        if self.kind is PostKind.GUESS:
            return 2 * n + 2
        return n + 2
```

Module level:

```python
MAX_GUESS = (SLIDES_PER_POST - 1) // 2  # two slides a title, within a post's slides


def cover_kicker(post: ListPost) -> str:
    """The pill on a non-chapter cover: what the post holds."""
    n = len(post.items)
    if post.kind is PostKind.SIMILAR:
        return "IF YOU LIKED"
    if post.kind is PostKind.VERSUS:
        return f"{(n + 1) // 2} ROUNDS" if n > 2 else "1 ROUND"
    if post.kind is PostKind.GUESS:
        return f"GUESS {n}"
    if post.kind is PostKind.CHARACTERS:
        return f"TOP {n}"
    return f"{n} PICK" if n == 1 else f"{n} PICKS"
```

In `draft.py`, `check_picks(title, items, kind=PostKind.LIST)`: keep the existing checks except the MAX_ITEMS one, then:

```python
    most = {PostKind.VERSUS: 2 * MAX_ITEMS, PostKind.GUESS: MAX_GUESS}.get(kind, MAX_ITEMS)
    if len(items) > most:
        raise DraftError(f"{len(items)} titles — a {kind.value} post fits at most {most}")
    if kind is PostKind.VERSUS and len(items) % 2:
        raise DraftError(f"{len(items)} titles — a versus post takes them in pairs; add or drop one")
    if kind is PostKind.CHARACTERS:
        bare = [i.manhwa.title for i in items if i.character is None]
        if bare:
            raise DraftError(f"pick a character for {', '.join(bare)}")
```

(`MAX_GUESS` imported from `domain.post`; `draft.py` already imports from it.)

- [ ] **Step 4:** run the new tests plus `tests/unit/test_draft*.py tests/unit/test_post*.py` → PASS.
- [ ] **Step 5:** commit `feat: post kinds in the model`.

---

### Task 2: AniList — recommendations and characters

**Files:**
- Modify: `src/manhwatok/adapters/anilist.py` (queries `_RECOMMEND`, `_CHARACTERS`; methods)
- Modify: `src/manhwatok/ports/metadata.py` (Protocol: `find`, `recommendations`, `characters`)
- Modify: `tests/unit/fakes.py` (`FakeMetadata`)
- Test: `tests/unit/test_anilist.py` (add; uses the file's existing httpx MockTransport pattern)

**Interfaces — Produces:**
- `recommendations(anilist_id: int, limit: int = 25) -> list[Manhwa]` — best rated first, the seed dropped, adult dropped.
- `characters(ids: list[int]) -> dict[int, list[CharacterPick]]` — per title, pictured characters most favourited first, `index` = position in that list, at most `QUAD_PICTURES`.
- `FakeMetadata.recommended: dict[int, list[Manhwa]]`, `FakeMetadata.cast: dict[int, list[CharacterPick]]`.

- [ ] **Step 1: failing tests** (append to `tests/unit/test_anilist.py`; reuse its helper that builds an `AniListSource` over a canned JSON response — read the top of the file for its name):

```python
def test_recommendations_are_the_seeds_rated_titles(canned):
    media = {"id": 1, "recommendations": {"nodes": [
        {"mediaRecommendation": {"id": 2, "title": {"english": "B", "romaji": "B"}, "status": "FINISHED", "isAdult": False}},
        {"mediaRecommendation": None},
        {"mediaRecommendation": {"id": 3, "title": {"english": "Adult", "romaji": "A"}, "status": "FINISHED", "isAdult": True}},
    ]}}
    source = canned({"data": {"Media": media}})
    assert [m.title for m in source.recommendations(1)] == ["B"]


def test_characters_follow_the_picture_order(canned):
    edges = [
        {"role": "MAIN", "node": {"name": {"full": "Jin"}, "favourites": 90, "image": {"large": "https://x/jin.png"}}},
        {"role": "MAIN", "node": {"name": {"full": "Nobody"}, "favourites": 80, "image": {"large": "https://x/default.jpg"}}},
        {"role": "SUPPORTING", "node": {"name": {"full": "Hae"}, "favourites": 70, "image": {"large": "https://x/hae.png"}}},
    ]
    source = canned({"data": {"Page": {"media": [{"id": 7, "characters": {"edges": edges}}]}}})
    picks = source.characters([7])[7]
    assert [(p.name, p.role, p.index) for p in picks] == [("Jin", "MAIN", 0), ("Hae", "SUPPORTING", 1)]
```

If `test_anilist.py` has no such fixture, add one:

```python
@pytest.fixture
def canned():
    def make(body):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
        return AniListSource(httpx.Client(transport=transport))
    return make
```

- [ ] **Step 2:** run → FAIL (no attribute).

- [ ] **Step 3: implement.** Queries (fields as `_FIND` plus `isAdult`):

```python
_RECOMMEND = """
query ($id: Int, $perPage: Int) {
  Media(id: $id, type: MANGA) {
    recommendations(sort: [RATING_DESC], perPage: $perPage) {
      nodes { mediaRecommendation {
        id isAdult countryOfOrigin
        title { english romaji } status chapters startDate { year } genres
        tags { name rank isMediaSpoiler } averageScore popularity
        coverImage { extraLarge color } bannerImage
        characters(sort: FAVOURITES_DESC, perPage: 8) { nodes { image { large } } }
        synonyms description(asHtml: false) siteUrl
      } }
    }
  }
}
"""

_CHARACTERS = """
query ($ids: [Int]) {
  Page(page: 1, perPage: 50) {
    media(id_in: $ids, type: MANGA) {
      id
      characters(sort: FAVOURITES_DESC, perPage: 8) {
        edges { role node { name { full } favourites image { large } } }
      }
    }
  }
}
"""
```

Methods on `AniListSource`:

```python
    def recommendations(self, anilist_id: int, limit: int = 25) -> list[Manhwa]:
        """What AniList's readers recommend to someone who liked the title, best rated first.
        Korean titles first, as everything else manhwatok suggests; adult ones never."""
        data = self._post(_RECOMMEND, {"id": anilist_id, "perPage": limit})
        nodes = ((data.get("Media") or {}).get("recommendations") or {}).get("nodes") or []
        found = [n["mediaRecommendation"] for n in nodes if n and n.get("mediaRecommendation")]
        found = [m for m in found if not m.get("isAdult") and m["id"] != anilist_id]
        found.sort(key=lambda m: m.get("countryOfOrigin") != "KR")  # stable: rating order kept
        return [_to_manhwa(m) for m in found]

    def characters(self, ids: list[int]) -> dict[int, list[CharacterPick]]:
        """Each title's pictured characters with their names, in `Manhwa.characters` order."""
        if not ids:
            return {}
        data = self._post(_CHARACTERS, {"ids": list(ids)})
        found: dict[int, list[CharacterPick]] = {}
        for m in data["Page"]["media"]:
            picks: list[CharacterPick] = []
            for edge in (m.get("characters") or {}).get("edges") or []:
                node = (edge or {}).get("node") or {}
                url = (node.get("image") or {}).get("large") or ""
                if not url or "default" in url:
                    continue  # unpictured: not in Manhwa.characters either
                picks.append(CharacterPick(
                    name=(node.get("name") or {}).get("full") or "?",
                    role=edge.get("role") or "",
                    favourites=node.get("favourites") or 0,
                    index=len(picks),
                ))
            found[m["id"]] = picks[:QUAD_PICTURES]
        return found
```

Port additions in `MetadataSource`:

```python
    def find(self, text: str, limit: int = 10) -> list[Manhwa]: ...

    def recommendations(self, anilist_id: int, limit: int = 25) -> list[Manhwa]:
        """What readers of the title recommend next, best rated first."""
        ...

    def characters(self, ids: list[int]) -> dict[int, list[CharacterPick]]:
        """Pictured characters by title id, in `Manhwa.characters` order."""
        ...
```

`FakeMetadata`: `self.recommended: dict[int, list[Manhwa]] = {}`, `self.cast: dict[int, list[CharacterPick]] = {}`, `recommendations = lambda self, i, limit=25: list(self.recommended.get(i, []))[:limit]`, `characters = lambda self, ids: {i: list(self.cast.get(i, [])) for i in ids}` (written as normal methods).

- [ ] **Step 4:** run anilist + fakes users (`uv run pytest tests/unit -q -k "anilist or suggest"`) → PASS.
- [ ] **Step 5:** commit `feat(anilist): recommendations and named characters`.

---

### Task 3: `similar` — If you liked X (and kind-aware covers/captions)

**Files:**
- Create: `src/manhwatok/app/kind_post.py`
- Modify: `src/manhwatok/app/build_post.py` (`kind`, `seed` passed through `create_post`/`store_new_post`/`save_new_post`/`build_post`; `check_picks(..., kind)`)
- Modify: `src/manhwatok/adapters/layout.py` (`layout_cover(..., kicker: str | None = None)`, `layout_magazine(..., kicker: str | None = None)`)
- Modify: `src/manhwatok/adapters/pillow_renderer.py` (`_cover_text` passes `cover_kicker(post)`), `src/manhwatok/adapters/cover_designs.py` (`magazine_slide` passes it)
- Modify: `src/manhwatok/domain/caption.py`
- Test: `tests/unit/test_kind_post.py`, `tests/unit/test_caption.py`

**Interfaces — Consumes:** Task 1 `PostKind`, `cover_kicker`; Task 2 `recommendations`.
**Produces:**
- `similar_candidates(seed: Manhwa, account: Account | None, metadata, chapters, history, now, allow_repeats=False, progress=_noop) -> list[Manhwa]` — raises `ManhwatokError(f"no recommendations for {seed.title}…")` when empty after filtering.
- `similar_title(seed: Manhwa) -> str` = `f"If you liked *{seed.title}*"`.
- `create_post(..., kind: PostKind = LIST, seed: Manhwa | None = None)` and the same two keywords on `store_new_post` / `save_new_post` / `build_post`.

- [ ] **Step 1: failing tests**

```python
# tests/unit/test_kind_post.py
from datetime import datetime, timezone

import pytest

from manhwatok.app.kind_post import similar_candidates, similar_title
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError
from tests.unit.fakes import FakeMetadata, InMemoryHistory, manhwa

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


def test_similar_takes_the_seeds_recommendations_minus_blocked_and_recent():
    seed = manhwa(anilist_id=1, title="Seed")
    a, b, c = (manhwa(anilist_id=i, title=t, genres=g) for i, t, g in
               ((2, "A", ["Action"]), (3, "B", ["Romance"]), (4, "C", ["Action"])))
    meta = FakeMetadata()
    meta.recommended[1] = [a, b, c]
    history = InMemoryHistory()
    history.record("reads", "p0", [4], NOW)
    acct = Account(handle="reads", block_genres=["Romance"])
    found = similar_candidates(seed, acct, meta, None, history, NOW)
    assert [m.title for m in found] == ["A"]


def test_similar_without_recommendations_says_so():
    with pytest.raises(ManhwatokError, match="no recommendations for Seed"):
        similar_candidates(manhwa(anilist_id=1, title="Seed"), None, FakeMetadata(), None, InMemoryHistory(), NOW)


def test_similar_title_stars_the_seed():
    assert similar_title(manhwa(title="Omniscient Reader")) == "If you liked *Omniscient Reader*"
```

(If `tests/unit/fakes.py` names its in-memory history differently, use that; grep `def record` in fakes.)

```python
# tests/unit/test_caption.py (append)
def test_a_similar_post_names_its_seed():
    from manhwatok.domain.caption import upload_description
    from manhwatok.domain.models import PostKind
    p = post(kind=PostKind.SIMILAR, seed=manhwa(anilist_id=99, title="Seed"))
    assert upload_description(p).startswith("If you liked Seed, read:\n1. ")
```

Renderer test (append to `tests/unit/test_pillow_renderer.py`):

```python
def test_a_similar_cover_says_if_you_liked(tmp_path, monkeypatch):
    from manhwatok.adapters import pillow_renderer
    from manhwatok.domain.models import PostKind

    seen = []
    real = pillow_renderer.layout_cover
    monkeypatch.setattr(pillow_renderer, "layout_cover", lambda *a, **k: seen.append(k.get("kicker")) or real(*a, **k))
    PillowRenderer().render(_post(2).model_copy(update={"kind": PostKind.SIMILAR}), _art({1: None, 2: None}), tmp_path / "o")
    assert "IF YOU LIKED" in seen
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3: implement.** `app/kind_post.py`:

```python
"""Building the post kinds beyond a plain list: where their titles come from."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from manhwatok.app.suggest import _drop_blocked, _fill_chapters
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Manhwa, SearchQuery
from manhwatok.domain.text import clean_names
from manhwatok.ports.metadata import ChapterSource, MetadataSource
from manhwatok.ports.store import HistoryRepository


def _noop(_: str) -> None:
    pass


def similar_title(seed: Manhwa) -> str:
    return f"If you liked *{seed.title}*"


def similar_candidates(
    seed: Manhwa,
    account: Account | None,
    metadata: MetadataSource,
    chapters: ChapterSource | None,
    history: HistoryRepository,
    now: datetime,
    allow_repeats: bool = False,
    progress: Callable[[str], None] = _noop,
) -> list[Manhwa]:
    """The seed's AniList recommendations, less what the account blocks or posted within its
    repeat window, as a list search's results are."""
    found = metadata.recommendations(seed.anilist_id)
    if account is not None:
        query = SearchQuery(
            exclude_genres=clean_names(account.block_genres),
            exclude_tags=clean_names(account.block_tags),
        )
        found = _drop_blocked(found, query)
        if not allow_repeats:
            recent = history.recent(account.handle, now - timedelta(days=account.repeat_days))
            found = [m for m in found if m.anilist_id not in recent]
    if not found:
        raise ManhwatokError(
            f"no recommendations for {seed.title} on AniList"
            + ("" if account is None else " that the account hasn't posted or blocked")
        )
    return _fill_chapters(found, chapters, progress)
```

(If `SearchQuery` has required fields, pass the minimum; check `domain/models.py` SearchQuery.) Rename `_drop_blocked`/`_fill_chapters` imports to public names only if a linter complains — keep them as is otherwise.

`build_post.py`: add `kind: PostKind = PostKind.LIST, seed: Manhwa | None = None` to `create_post` (set on the `ListPost`), `store_new_post` (call `check_picks(title, items, kind)`), `save_new_post`, `build_post`; thread them through.

`layout.py`: `layout_cover(title, count, byline="", kicker=None)` uses `kicker or (f"{count} PICK" if count == 1 else f"{count} PICKS")`; same for `layout_magazine`'s label. `pillow_renderer._cover_text`: `layout_cover(post.title, len(post.items), _byline(post), kicker=cover_kicker(post))`; bar count stays `len(post.items)` except versus uses rounds: `count = (len(post.items)+1)//2 if post.kind is PostKind.VERSUS else len(post.items)`. `cover_designs.magazine_slide`: `layout_magazine(post.title, len(post.items), _byline(post), kicker=cover_kicker(post))`.

`caption.py`, `upload_description`:

```python
    if post.kind is PostKind.SIMILAR and post.seed is not None:
        picks = "\n".join(f"{i}. {it.manhwa.title}" for i, it in enumerate(post.items, 1))
        return f"If you liked {post.seed.title}, read:\n{picks}\n\n{post.hashtags}".strip()
```

- [ ] **Step 4:** `uv run pytest tests/unit -q` → PASS.
- [ ] **Step 5:** commit `feat: if-you-liked posts`.

---

### Task 4: `versus`

**Files:**
- Create: `src/manhwatok/adapters/kind_slides.py`
- Modify: `src/manhwatok/adapters/layout.py` (`layout_versus`)
- Modify: `src/manhwatok/adapters/pillow_renderer.py` (`render` dispatch; `end_slide(post, images, names=None)`)
- Modify: `src/manhwatok/domain/caption.py`
- Test: `tests/unit/test_kind_slides.py`, `tests/unit/test_layout.py`, `tests/unit/test_caption.py`

**Interfaces — Produces:**
- `layout_versus(name_a, pill_a, name_b, pill_b, byline="") -> VersusLayout` with `a_name, a_pill, b_name, b_pill: Placed|Pill`, `badge: Box` (centre (540, 960), 200×200), `byline`, `text_boxes()`.
- `kind_slides.versus_slide(post, pair: tuple[PostItem, PostItem], loaded, picker) -> Image`
- `kind_slides.middle_slides(post, loaded, picker, item_slide) -> list[Image]` — the one dispatch the renderer calls for non-list kinds (`item_slide` is `PillowRenderer.item_slide`, passed in to avoid an import cycle).
- `kind_slides.end_names(post) -> list[str]` — the end slide's recap rows per kind.
- `end_slide(self, post, images, names: list[str] | None = None)` — `names` defaults to item titles; row number colours only when `len(names) == len(post.items)`.

- [ ] **Step 1: failing tests**

```python
# tests/unit/test_kind_slides.py
from PIL import Image

from manhwatok.adapters.pillow_renderer import PillowRenderer
from manhwatok.domain.models import PostKind
from manhwatok.domain.post import PostItem
from manhwatok.ports.posts import SlideArt
from tests.unit.fakes import cover_file, manhwa, post


def _px(path, xy):
    with Image.open(path) as img:
        return img.convert("RGB").getpixel(xy)


def _versus(tmp_path, n=4):
    colours = [(220, 30, 30), (30, 30, 230), (30, 210, 30), (230, 210, 30)]
    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in range(1, n + 1)]
    art = {i: SlideArt(cover_file(tmp_path / "c", i, color=colours[i - 1]), None) for i in range(1, n + 1)}
    return post(items=items, kind=PostKind.VERSUS), art


def test_versus_draws_one_slide_per_pair_top_against_bottom(tmp_path):
    p, art = _versus(tmp_path)
    paths = PillowRenderer().render(p, art, tmp_path / "out")
    assert len(paths) == 4  # cover, 2 rounds, end
    r, g, b = _px(paths[1], (60, 200))
    assert r > b + 80  # T1 on top
    r, g, b = _px(paths[1], (60, 1200))
    assert b > r + 80  # T2 below


def test_versus_has_a_vs_badge_in_the_accent(tmp_path):
    from manhwatok.domain.color import hex_to_rgb, readable_accent

    p, art = _versus(tmp_path)
    paths = PillowRenderer().render(p, art, tmp_path / "out")
    accent = hex_to_rgb(readable_accent(p.accent))
    assert all(abs(a - b) < 40 for a, b in zip(_px(paths[1], (540, 900)), accent))


def test_versus_end_recaps_the_rounds():
    from manhwatok.adapters.kind_slides import end_names

    p = post(items=[PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in (1, 2)], kind=PostKind.VERSUS)
    assert end_names(p) == ["T1 vs T2"]
```

```python
# tests/unit/test_layout.py (append)
def test_versus_text_sits_in_each_half():
    from manhwatok.adapters.layout import layout_versus

    v = layout_versus(LONG_NAME, "ongoing", LONG_NAME, "finished", BY)
    assert all(SAFE.contains(b) or b.y < SAFE.y for b in v.text_boxes())
    assert v.a_name.box.bottom < 960 - 100 and v.b_name.box.y > 960 + 100
```

```python
# tests/unit/test_caption.py (append)
def test_a_versus_post_lists_its_rounds():
    from manhwatok.domain.caption import upload_description
    from manhwatok.domain.models import PostKind
    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in (1, 2)]
    assert upload_description(post(items=items, kind=PostKind.VERSUS)).startswith("1. T1 vs T2")
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3: implement.**

`layout.py`:

```python
HALF = SLIDE_H // 2
VS_SIZE = 200


@dataclass(frozen=True)
class VersusLayout:
    a_name: Placed
    a_pill: Pill
    b_name: Placed
    b_pill: Pill
    badge: Box
    byline: Placed | None = None

    def text_boxes(self) -> list[Box]:
        return [self.a_name.box, self.a_pill.box, self.b_name.box, self.b_pill.box]


def layout_versus(name_a: str, pill_a: str, name_b: str, pill_b: str, byline: str = "") -> VersusLayout:
    """Each title's name and pill at the foot of its own half: the top one's above the badge,
    the bottom one's above the byline."""
    x = SAFE.x
    placed = []
    for name, label, bottom in ((name_a, pill_a, HALF - VS_SIZE // 2 - 40), (name_b, pill_b, SAFE.bottom)):
        name_t = fit_words(plain_words(name.upper() or "?"), display, ITEM_TEXT_W, 2, 62, 42, 1.08)
        pill = make_pill(label.upper(), bold, 32, ITEM_TEXT_W, x)
        tops = stack_up([name_t.height, pill.box.h], bottom)
        placed.append((Placed(name_t, x, tops[0], ITEM_TEXT_W), _at(pill, tops[1])))
    badge = Box((SLIDE_W - VS_SIZE) // 2, HALF - VS_SIZE // 2, VS_SIZE, VS_SIZE)
    return VersusLayout(placed[0][0], placed[0][1], placed[1][0], placed[1][1], badge, byline_of(byline))
```

`kind_slides.py`:

```python
"""The middle and end slides of the post kinds beyond a list: versus, guess, characters.
A similar post's slides are a list post's."""

from __future__ import annotations

from typing import Callable

from PIL import Image, ImageDraw

from manhwatok.adapters.fonts import display
from manhwatok.adapters.layout import HALF, SLIDE_W, layout_versus
from manhwatok.adapters.pillow_renderer import (
    DARK, SIZE, WHITE, _Art, _best_piece, _bottom_gradient, _byline, _crop_to,
    _accent_gradient, _draw_byline, _draw_pill, _draw_text,
)
from manhwatok.domain.color import hex_to_rgb, readable_accent
from manhwatok.domain.labels import chapter_label
from manhwatok.domain.models import PostKind
from manhwatok.domain.post import ListPost, PostItem
from manhwatok.ports.picker import PicturePicker

ItemSlide = Callable[[ListPost, int, dict], Image.Image]


def _art(loaded: dict[int, _Art], item: PostItem) -> _Art:
    return loaded.get(item.manhwa.anilist_id) or _Art(None, None, None, None)


def _half(post: ListPost, item: PostItem, loaded, picker) -> Image.Image:
    piece = _best_piece(_art(loaded, item), picker)
    size = (SLIDE_W, HALF)
    if piece is None:
        return _accent_gradient(size, readable_accent(item.manhwa.cover_color, post.accent))
    return _crop_to(piece, size, 0.3)


def versus_slide(post: ListPost, pair: tuple[PostItem, PostItem], loaded, picker: PicturePicker | None) -> Image.Image:
    a, b = pair
    accent = hex_to_rgb(readable_accent(post.accent))
    canvas = Image.new("RGBA", SIZE, (*DARK, 255))
    canvas.paste(_half(post, a, loaded, picker).convert("RGBA"), (0, 0))
    canvas.paste(_half(post, b, loaded, picker).convert("RGBA"), (0, HALF))
    # Each half darkens toward its own text: the top one toward the badge, the bottom one down.
    _gradient_at(canvas, HALF - 520, 520)
    _bottom_gradient(canvas, 760)
    layout = layout_versus(a.manhwa.title, chapter_label(a.manhwa), b.manhwa.title, chapter_label(b.manhwa), _byline(post))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, HALF - 6, SLIDE_W, HALF + 6), fill=accent)
    bx = layout.badge
    draw.ellipse((bx.x, bx.y, bx.right, bx.bottom), fill=accent, outline=DARK, width=8)
    draw.text((bx.x + bx.w // 2, bx.y + bx.h // 2), "VS", font=display(88), fill=DARK, anchor="mm")
    for name, pill in ((layout.a_name, layout.a_pill), (layout.b_name, layout.b_pill)):
        _draw_text(draw, name, WHITE, accent)
        _draw_pill(draw, pill, accent, filled=False)
    _draw_byline(canvas, layout.byline)
    return canvas


def end_names(post: ListPost) -> list[str]:
    items = post.items
    if post.kind is PostKind.VERSUS:
        return [f"{items[i].manhwa.title} vs {items[i + 1].manhwa.title}" for i in range(0, len(items) - 1, 2)]
    if post.kind is PostKind.CHARACTERS:
        return [f"{i.character.name} ({i.manhwa.title})" if i.character else i.manhwa.title for i in items]
    return [i.manhwa.title for i in items]


def middle_slides(post: ListPost, loaded, picker, item_slide: ItemSlide) -> list[Image.Image]:
    """The slides between cover and end, per kind."""
    if post.kind is PostKind.VERSUS:
        its = post.items
        return [versus_slide(post, (its[i], its[i + 1]), loaded, picker) for i in range(0, len(its) - 1, 2)]
    return [item_slide(post, i, loaded) for i in range(len(post.items))]
```

`_gradient_at` is new in `pillow_renderer.py` (import it in `kind_slides.py`); `_bottom_gradient` only darkens the slide's foot:

```python
def _gradient_at(canvas: Image.Image, top: int, height: int) -> None:
    """`_bottom_gradient`'s curve over rows top … top+height of `canvas`."""
    alpha = []
    for y in range(height):
        t = y / (height - 1)
        a = 0.88 * t / 0.55 if t <= 0.55 else 0.88 + 0.12 * (t - 0.55) / 0.45
        alpha.append(round(255 * a))
    mask = Image.new("L", (1, height))
    mask.putdata(alpha)
    canvas.paste((0, 0, 0), (0, top, canvas.width, top + height), mask.resize((canvas.width, height)))
```

and `_bottom_gradient(canvas, h)` becomes a one-line wrapper: `_gradient_at(canvas, SLIDE_H - h, h)`.

`pillow_renderer.render` (non-chapter branch): replace the item-slides line with

```python
        from manhwatok.adapters.kind_slides import end_names, middle_slides

        slides += middle_slides(post, loaded, self._picker, self.item_slide)
        slides.append(self.end_slide(post, covers, end_names(post)))
```

`end_slide(self, post, images, names=None)`: `names = names or [it.manhwa.title for it in post.items]`; pass `names` to `layout_end`; colour a row's number from `post.items[i]` only when `len(names) == len(post.items)`, else the accent.

`caption.py`:

```python
    if post.kind is PostKind.VERSUS:
        its = post.items
        rounds = "\n".join(f"{n}. {its[i].manhwa.title} vs {its[i+1].manhwa.title}" for n, i in enumerate(range(0, len(its) - 1, 2), 1))
        return f"{rounds}\n\n{post.hashtags}".strip()
```

Default end texts for versus when the account kept the defaults: in `create_post`, if `kind is VERSUS and cta_title == DEFAULT_CTA_TITLE` → `cta_title = "Which one *wins?*"`; guess → `"How many did you *get?*"`; characters → `"Who's *your #1?*"`.

- [ ] **Step 4:** `uv run pytest tests/unit -q` → PASS.
- [ ] **Step 5:** commit `feat: versus posts`.

---

### Task 5: `guess`

**Files:**
- Modify: `src/manhwatok/adapters/layout.py` (`layout_guess`)
- Modify: `src/manhwatok/adapters/kind_slides.py` (`clue_piece`, `clue_slide`, dispatch)
- Modify: `src/manhwatok/domain/caption.py`
- Test: `tests/unit/test_kind_slides.py`, `tests/unit/test_layout.py`, `tests/unit/test_caption.py`

**Interfaces — Produces:**
- `layout_guess(number: int, hint: str, byline="") -> GuessLayout(label: Placed "GUESS", number: Placed "#n", hint: Placed, byline)`, all inside SAFE, ending at `COVER_BOTTOM`.
- `guess_hint(m: Manhwa) -> str` in `domain/labels.py`: first two genres · start year · status word (e.g. `"Action · Fantasy · 2018 · finished"`).
- `clue_piece(art: _Art, picker) -> Piece | None`: picker focus over `[custom, *gallery, character]` (any size), else the cover focus cut clear of text (the ClipPicker already trims lettering), zoomed to the middle 60% of the focus box.

- [ ] **Step 1: failing tests**

```python
# tests/unit/test_kind_slides.py (append)
def test_guess_puts_a_clue_before_each_reveal(tmp_path):
    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in (1, 2)]
    p = post(items=items, kind=PostKind.GUESS)
    paths = PillowRenderer().render(p, {1: SlideArt(None, None), 2: SlideArt(None, None)}, tmp_path / "o")
    assert len(paths) == 6  # cover, clue, reveal, clue, reveal, end


def test_the_clue_prefers_picked_art_over_the_lettered_cover(tmp_path):
    from manhwatok.adapters.kind_slides import clue_piece
    from manhwatok.adapters.pillow_renderer import _Art

    cover, pick = Image.new("RGB", (460, 650), (200, 30, 30)), Image.new("RGB", (600, 900), (30, 30, 200))
    img, _ = clue_piece(_Art(cover, None, None, pick), None)
    assert img is pick


def test_guess_hint():
    from manhwatok.domain.labels import guess_hint
    from manhwatok.domain.models import Status
    m = manhwa(genres=["Action", "Fantasy", "Drama"], start_year=2018, status=Status.FINISHED)
    assert guess_hint(m) == "Action · Fantasy · 2018 · finished"
```

```python
# tests/unit/test_layout.py (append)
def test_the_guess_layout_stays_in_the_safe_area():
    from manhwatok.adapters.layout import layout_guess
    g = layout_guess(16, LONG_HOOK, BY)
    assert all(SAFE.contains(b) for b in g.text_boxes())
    assert max(b.bottom for b in g.text_boxes()) <= COVER_BOTTOM
```

```python
# tests/unit/test_caption.py (append)
def test_a_guess_post_keeps_its_answers_below_the_fold():
    from manhwatok.domain.caption import upload_description
    from manhwatok.domain.models import PostKind
    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in (1, 2)]
    text = upload_description(post(items=items, kind=PostKind.GUESS))
    assert text.startswith("Guess all 2 before you swipe!") and "Answers:\n1. T1\n2. T2" in text
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3: implement.**

`labels.py`:

```python
def guess_hint(m: Manhwa) -> str:
    """What a guess post's clue tells: two genres, the year it began, whether it's done."""
    status = {Status.FINISHED: "finished", Status.RELEASING: "ongoing", Status.HIATUS: "on hiatus"}.get(m.status, "")
    parts = [*m.genres[:2], str(m.start_year) if m.start_year else "", status]
    return " · ".join(p for p in parts if p)
```

`layout.py`:

```python
@dataclass(frozen=True)
class GuessLayout:
    label: Placed
    number: Placed
    hint: Placed | None
    byline: Placed | None = None

    def text_boxes(self) -> list[Box]:
        return [b.box for b in (self.label, self.number, self.hint) if b is not None]


def layout_guess(number: int, hint: str, byline: str = "") -> GuessLayout:
    """"GUESS", the number big, the hint: stacked up to COVER_BOTTOM, clear of TikTok's caption."""
    x, w = SAFE.x, SAFE.w
    label = fit_words(plain_words("GUESS"), bold, w, 1, 64, 64, 1.0)
    big = fit_words(plain_words(f"#{number}"), display, w, 1, 300, 160, 1.0)
    hint_t = fit_words(plain_words(hint), body, w, 2, 44, 32, 1.3) if hint.strip() else None
    heights = [label.height, big.height] + ([hint_t.height] if hint_t else [])
    tops = stack_up(heights, COVER_BOTTOM)
    return GuessLayout(
        Placed(label, x, tops[0], w, "center"),
        Placed(big, x, tops[1], w, "center"),
        Placed(hint_t, x, tops[2], w, "center") if hint_t else None,
        byline_of(byline),
    )
```

`kind_slides.py`:

```python
CLUE_ZOOM = 0.6  # the clue shows the middle of the focus: enough to recognise, not to read


def clue_piece(art: _Art, picker: PicturePicker | None) -> Piece | None:
    """A clue's picture: picked art, scenes or a character before the cover, whose lettering
    names the title (the picker trims what text it finds)."""
    candidates = [img for img in (art.custom, *art.gallery, art.character) if img is not None]
    candidates = candidates or ([art.cover] if art.cover is not None else [])
    if not candidates:
        return None
    if picker is not None:
        found = picker.focus(candidates)
        img, (l, t, r, b) = (candidates[found[0].index], found[0].box) if found else (candidates[0], (0, 0, candidates[0].width, candidates[0].height))
    else:
        img = candidates[0]
        l, t, r, b = 0, 0, img.width, img.height
    w, h = (r - l) * CLUE_ZOOM, (b - t) * CLUE_ZOOM
    cx, cy = (l + r) / 2, t + (b - t) * 0.4
    return img, (round(cx - w / 2), round(max(t, cy - h / 2)), round(cx + w / 2), round(min(b, cy + h / 2)))


def clue_slide(post: ListPost, index: int, loaded, picker) -> Image.Image:
    item = post.items[index]
    accent_hex = readable_accent(post.accent)
    accent = hex_to_rgb(accent_hex)
    piece = clue_piece(_art(loaded, item), picker)
    canvas = (_focused(*piece, accent_hex) if piece else _accent_gradient(SIZE, accent_hex).convert("RGBA"))
    _bottom_gradient(canvas, COVER_GRADIENT_H)
    layout = layout_guess(index + 1, guess_hint(item.manhwa), _byline(post))
    draw = ImageDraw.Draw(canvas)
    _draw_text(draw, layout.label, WHITE, WHITE)
    big = layout.number
    draw.text((big.line_x(0), big.text.baselines(big.y)[0]), big.text.line_text(0), font=big.text.font,
              fill=accent, stroke_width=6, stroke_fill=DARK, anchor="ls")
    if layout.hint:
        _draw_text(draw, layout.hint, WHITE, accent)
    _draw_byline(canvas, layout.byline)
    return canvas
```

(import `Piece`, `_focused`, `COVER_GRADIENT_H` from `pillow_renderer`; `layout_guess` from layout; `guess_hint` from labels.)

`middle_slides`: add

```python
    if post.kind is PostKind.GUESS:
        out = []
        for i in range(len(post.items)):
            out += [clue_slide(post, i, loaded, picker), item_slide(post, i, loaded)]
        return out
```

`render_post._art_paths`: guess needs characters and galleries for every item — extend the `wanted` list to all items when `post.kind is GUESS` (as for `ArtStyle.CHARACTER`), and load gallery / character in `PillowRenderer.render`'s `loaded` for every item when `post.kind is PostKind.GUESS` (add `or post.kind is PostKind.GUESS` to both conditions).

`caption.py`:

```python
    if post.kind is PostKind.GUESS:
        answers = "\n".join(f"{i}. {it.manhwa.title}" for i, it in enumerate(post.items, 1))
        lead = f"Guess all {len(post.items)} before you swipe!"
        return f"{lead}\n.\n.\n.\nAnswers:\n{answers}\n\n{post.hashtags}".strip()
```

- [ ] **Step 4:** `uv run pytest tests/unit -q` → PASS.
- [ ] **Step 5:** commit `feat: guess-the-manhwa posts`.

---

### Task 6: `characters`

**Files:**
- Modify: `src/manhwatok/app/kind_post.py` (`with_characters`)
- Modify: `src/manhwatok/app/render_post.py` (`_art_paths` fetches the picked character per item)
- Modify: `src/manhwatok/adapters/kind_slides.py` (characters dispatch)
- Modify: `src/manhwatok/adapters/pillow_renderer.py:item_slide` (characters: portrait + character name)
- Modify: `src/manhwatok/domain/caption.py`
- Test: `tests/unit/test_kind_post.py`, `tests/unit/test_kind_slides.py`, `tests/unit/test_caption.py`

**Interfaces — Produces:**
- `with_characters(items: list[PostItem], metadata, choice: dict[int, int] | None = None) -> list[PostItem]`: one `metadata.characters(ids)` call; each item gets `character = picks[choice.get(id, 0)]` and `manhwa.character_urls` refreshed to the looked-up pictures' order (`manhwa.model_copy`); a title with no pictured character raises `ManhwatokError(f"{title} has no pictured characters on AniList")`. Needs the URLs: extend `CharacterPick` with `image_url: str = ""` (set in Task 2's adapter from `url`) and refresh `character_urls = [p.image_url for p in picks]`.
- `character_choices(items, metadata) -> dict[int, list[CharacterPick]]` (for the web/TUI select).

- [ ] **Step 1: failing tests**

```python
# tests/unit/test_kind_post.py (append)
from manhwatok.app.kind_post import with_characters
from manhwatok.domain.models import CharacterPick
from manhwatok.domain.post import PostItem


def _cast(meta):
    meta.cast[1] = [CharacterPick(name="Jin", index=0, image_url="https://x/jin.png"),
                    CharacterPick(name="Hae", index=1, image_url="https://x/hae.png")]


def test_characters_take_the_chosen_one_and_refresh_the_pictures():
    meta = FakeMetadata()
    _cast(meta)
    items = with_characters([PostItem(manhwa=manhwa(anilist_id=1, title="T1"))], meta, {1: 1})
    assert items[0].character.name == "Hae"
    assert items[0].manhwa.character_urls == ["https://x/jin.png", "https://x/hae.png"]


def test_a_title_without_characters_is_refused_by_name():
    with pytest.raises(ManhwatokError, match="T9 has no pictured characters"):
        with_characters([PostItem(manhwa=manhwa(anilist_id=9, title="T9"))], FakeMetadata())
```

```python
# tests/unit/test_kind_slides.py (append)
def test_a_character_slide_shows_the_portrait_and_the_name(tmp_path, monkeypatch):
    from manhwatok.adapters import pillow_renderer
    from manhwatok.domain.models import CharacterPick

    names = []
    real = pillow_renderer.layout_item
    monkeypatch.setattr(pillow_renderer, "layout_item", lambda rank, name, *a, **k: names.append(name) or real(rank, name, *a, **k))
    item = PostItem(manhwa=manhwa(anilist_id=1, title="T1"), character=CharacterPick(name="Jin"))
    portrait = cover_file(tmp_path / "ch", 1, color=(30, 210, 30), size=(230, 345))
    paths = PillowRenderer().render(post(items=[item], kind=PostKind.CHARACTERS), {1: SlideArt(None, None, portrait)}, tmp_path / "o")
    assert "Jin" in names
    assert _px(paths[1], (540, 700))[1] > 150  # the green portrait fills the card area
```

```python
# tests/unit/test_caption.py (append)
def test_a_characters_post_names_who_and_from_where():
    from manhwatok.domain.caption import upload_description
    from manhwatok.domain.models import CharacterPick, PostKind
    item = PostItem(manhwa=manhwa(anilist_id=1, title="T1"), character=CharacterPick(name="Jin"))
    assert upload_description(post(items=[item], kind=PostKind.CHARACTERS)).startswith("1. Jin (T1)")
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3: implement.**

`kind_post.py`:

```python
def character_choices(items: list[PostItem], metadata: MetadataSource) -> dict[int, list[CharacterPick]]:
    return metadata.characters([i.manhwa.anilist_id for i in items])


def with_characters(items, metadata, choice=None) -> list[PostItem]:
    """Each pick with its character: `choice[id]` (an index into its choices), else its most
    favourited. The title's pictures are refreshed so the character's index finds its image."""
    cast = character_choices(items, metadata)
    out = []
    for item in items:
        picks = cast.get(item.manhwa.anilist_id) or []
        if not picks:
            raise ManhwatokError(f"{item.manhwa.title} has no pictured characters on AniList")
        chosen = picks[min(max((choice or {}).get(item.manhwa.anilist_id, 0), 0), len(picks) - 1)]
        m = item.manhwa.model_copy(update={
            "character_urls": [p.image_url for p in picks],
            "character_url": picks[0].image_url,
        })
        hook = item.hook or " · ".join(x for x in (chosen.role.title(), m.title) if x)
        out.append(item.model_copy(update={"manhwa": m, "character": chosen, "hook": hook}))
    return out
```

`render_post._art_paths`: when `post.kind is PostKind.CHARACTERS`, fetch per item `tools.covers.get_character(m, item.character.index)` (cached first via `cached_character(m, index)`, same first-failure rule as `_fetch_each`) into the `characters` dict instead of index 0.

`PillowRenderer.render` `loaded`: load `one.character` for every item when `post.kind is PostKind.CHARACTERS`.

`PillowRenderer.item_slide`: at the top,

```python
        is_character = post.kind is PostKind.CHARACTERS and item.character is not None
        name = item.character.name if is_character else m.title
        pill = m.title if is_character else chapter_label(m)
        art_style = ArtStyle.CHARACTER if is_character else post.art
```

and use `name`, `pill`, `art_style` in `layout_item(...)` and in place of `post.art` for the style branches below (the character branch already prefers `art.character`).

`caption.py`:

```python
    if post.kind is PostKind.CHARACTERS:
        rows = "\n".join(
            f"{i}. {it.character.name} ({it.manhwa.title})" if it.character else f"{i}. {it.manhwa.title}"
            for i, it in enumerate(post.items, 1)
        )
        return f"{rows}\n\n{post.hashtags}".strip()
```

- [ ] **Step 4:** `uv run pytest tests/unit -q` → PASS.
- [ ] **Step 5:** commit `feat: character ranking posts`.

---

### Task 7: Web — New post tabs for every kind

**Files:**
- Modify: `src/manhwatok/web/routes/new.py` (`new_page` kinds; `/new/search` carries `kind`; new `/new/similar`; `/new/save` reads `kind`, `seed`, `character-<id>`)
- Modify: `src/manhwatok/web/drafts.py` (`Draft.kind: str = "list"`, `Draft.seed: Manhwa | None = None`, `Draft.cast: dict[int, list] = {}`; `add(..., kind="list", seed=None, cast=None)`)
- Modify: `src/manhwatok/web/templates/new.html`, `_new_results.html`, `_picks_list.html`
- Modify: `src/manhwatok/web/templates/_post_detail.html` (kind line)
- Test: `tests/web/test_new_kinds.py`

**Interfaces — Consumes:** Tasks 3–6 (`similar_candidates`, `similar_title`, `character_choices`, `with_characters`, `store_new_post(..., kind, seed)`).

- [ ] **Step 1: failing tests** (`tests/web/test_new_kinds.py`, modelled on `tests/web/test_new.py` — copy its ctx/metadata setup helpers; read that file's top first):

```python
import pytest

pytest.importorskip("fastapi")

from manhwatok.domain.models import CharacterPick, PostKind  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import FakeMetadata, manhwa  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402


def _ctx(tmp_path, n=4):
    meta = FakeMetadata(results=[manhwa(anilist_id=i, title=f"T{i}") for i in range(1, n + 1)])
    return make_ctx(tmp_path, metadata=meta), meta


@pytest.mark.parametrize("kind", ["similar", "versus", "guess", "characters"])
def test_every_kind_has_a_tab(tmp_path, kind):
    ctx, _ = _ctx(tmp_path)
    with client_for(ctx) as client:
        html = client.get(f"/new?type={kind}").text
    assert f'href="/new?type={kind}" aria-current="page"' in html


def test_a_versus_search_saves_a_versus_post(tmp_path):
    ctx, _ = _ctx(tmp_path)
    with client_for(ctx) as client:
        html = client.post("/new/search", data={"kind": "versus", "limit": "4"}).text
        draft = html.split('name="draft" value="')[1].split('"')[0]
        client.post("/new/save", data={"draft": draft, "title": "Which wins", "pick": ["1", "2", "3", "4"]})
    (saved,) = ctx.tools.posts.list()
    assert saved.kind is PostKind.VERSUS and len(saved.items) == 4


def test_an_odd_versus_is_refused(tmp_path):
    ctx, _ = _ctx(tmp_path)
    with client_for(ctx) as client:
        html = client.post("/new/search", data={"kind": "versus", "limit": "3"}).text
        draft = html.split('name="draft" value="')[1].split('"')[0]
        r = client.post("/new/save", data={"draft": draft, "title": "X", "pick": ["1", "2", "3"]})
    assert "pairs" in r.headers.get("HX-Trigger", "")


def test_a_similar_search_starts_from_the_seed(tmp_path):
    ctx, meta = _ctx(tmp_path)
    meta.recommended[1] = [manhwa(anilist_id=5, title="R5"), manhwa(anilist_id=6, title="R6")]
    with client_for(ctx) as client:
        html = client.post("/new/similar", data={"seed": "T1"}).text
        draft = html.split('name="draft" value="')[1].split('"')[0]
        assert 'value="If you liked *T1*"' in html
        client.post("/new/save", data={"draft": draft, "title": "If you liked *T1*", "pick": ["5", "6"]})
    (saved,) = ctx.tools.posts.list()
    assert saved.kind is PostKind.SIMILAR and saved.seed.title == "T1"


def test_a_characters_save_takes_the_chosen_character(tmp_path):
    ctx, meta = _ctx(tmp_path, 1)
    meta.cast[1] = [CharacterPick(name="Jin", index=0, image_url="u0"), CharacterPick(name="Hae", index=1, image_url="u1")]
    with client_for(ctx) as client:
        html = client.post("/new/search", data={"kind": "characters", "limit": "1"}).text
        assert "Hae" in html  # the select lists the title's characters
        draft = html.split('name="draft" value="')[1].split('"')[0]
        client.post("/new/save", data={"draft": draft, "title": "Top", "pick": ["1"], "character-1": "1"})
    (saved,) = ctx.tools.posts.list()
    assert saved.items[0].character.name == "Hae"
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3: implement.**

`new.py`:
- `KINDS = {"list": "Recommendation list", "similar": "If you liked", "versus": "Versus", "guess": "Guess", "characters": "Characters", "chapter": "Chapter"}`; `new_page`: `kind = type if type in KINDS else "list"`, pass `kinds=KINDS`.
- `/new/search`: add `kind: str = Form("list")`; `drafts.add(results, handle, theme, kind=kind, cast=character_choices(prefill, ctx.metadata) if kind == "characters" else None)`; pass `kind`, `cast` to the template.
- `/new/similar` (POST, form `account`, `seed`, `repeats`, `chapters`): resolve the seed with `resolve_title(seed, ctx.metadata)` (from `app/chapter_post.py`) — or `ctx.store.chapters`-tracked id if numeric; `results = similar_candidates(...)`; `drafts.add(results, handle, None, kind="similar", seed=seed_m)`; render `_new_results.html` with `title=similar_title(seed_m)`, `kind="similar"`.
- `/new/save`: `kind = PostKind(draft.kind)`; build items as now; if characters: `items = with_characters(items, ctx.metadata, {int(p): int(form.get(f"character-{p}", 0) or 0) for p in picks})`; `store_new_post(..., kind=kind, seed=draft.seed)`. Errors from `with_characters`/`check_picks` return `done(request, str(e), "error")` as now.

`new.html`: tabs loop

```html
  <nav class="tabs" aria-label="Kind of post">
    {% for k, label in kinds.items() %}<a href="/new{% if k != 'list' %}?type={{ k }}{% endif %}" {% if kind == k %}aria-current="page"{% endif %}>{{ label }}</a>{% endfor %}
  </nav>
```

Body: `{% if kind == "chapter" %}…{% elif kind == "similar" %}<similar form>{% else %}<list form with <input type="hidden" name="kind" value="{{ kind }}">>{% endif %}`. Similar form: account select, `seed` (tracked-title select `name="seed"` with titles' names + free-text `name="seed_text"`; the route uses whichever is filled), repeats + chapters checkboxes, button "Find recommendations", `hx-post="/new/similar" hx-target="#results"`. A per-kind hint line under the list form: versus "Pick an even number: 1 vs 2, 3 vs 4…", guess "Up to 16 titles; each gets a clue and a reveal.", characters "Each pick shows one of its characters — choose which below."

`_new_results.html`: add `<input type="hidden" name="kind" value="{{ kind }}">` (informational) and pass `kind`, `cast` into `_picks_list.html`.

`_picks_list.html` per row: for versus, `{% if kind == "versus" %}<span class="round">{{ (loop.index0 // 2) + 1 }}{{ "A" if loop.index0 % 2 == 0 else "B" }}</span>{% endif %}` before the image (CSS `.pick .round { font-weight: 700; color: var(--accent); }`; note: numbering is by render order at save time, not live on reorder — acceptable); for characters,

```html
{% if kind == "characters" %}
<select name="character-{{ item.manhwa.anilist_id }}" aria-label="Character for {{ item.manhwa.title }}">
  {% for c in cast.get(item.manhwa.anilist_id, []) %}<option value="{{ loop.index0 }}">{{ c.name }}{% if c.role %} · {{ c.role | lower }}{% endif %}</option>{% endfor %}
</select>
{% endif %}
```

`_post_detail.html`: under the status line, `{% if d.post.kind.value not in ("list", "chapter") %}<span class="muted">· {{ d.post.kind.value }}</span>{% endif %}`.

- [ ] **Step 4:** `uv run pytest tests/web -q` → PASS; start `uv run manhwatok web` (see README for the command) and open `/new?type=versus` etc. to eyeball the tabs.
- [ ] **Step 5:** commit `feat(web): new-post tabs for every kind`.

---

### Task 8: CLI and TUI

**Files:**
- Modify: `src/manhwatok/cli.py` (`build --kind`, `build --like`)
- Modify: `src/manhwatok/domain/draft.py` (4th field `| N` = character choice for characters drafts)
- Modify: `src/manhwatok/app/build_post.py:build_post` (kind-aware: characters applies `with_characters` after parsing)
- Modify: `src/manhwatok/tui/screens/build.py` (mode radio with all kinds; class `-kind-<k>`)
- Test: `tests/unit/test_cli_kinds.py`, `tests/tui/test_build_kinds.py`

**Interfaces — Consumes:** everything above.

- [ ] **Step 1: failing tests**

```python
# tests/unit/test_cli_kinds.py — reuse test_cli_posts.py's `wire` fixture (import it or copy)
def test_build_kind_versus_makes_a_versus_post(wire):
    repo, meta = wire(results=4)          # adapt to the fixture's real signature
    out = runner.invoke(app, ["build", "--tag", "Action", "--kind", "versus", "--limit", "4"])
    assert out.exit_code == 0, out.output
    (saved,) = repo.list()
    assert saved.kind.value == "versus"


def test_build_like_makes_a_similar_post(wire):
    repo, meta = wire(results=1)
    meta.recommended[1] = [manhwa(anilist_id=5, title="R5")]
    out = runner.invoke(app, ["build", "--like", "T1"])
    assert out.exit_code == 0, out.output
    (saved,) = repo.list()
    assert saved.kind.value == "similar" and saved.title == "If you liked *T1*"


def test_parse_choices_reads_the_fourth_field():
    from manhwatok.domain.draft import parse_choices
    assert parse_choices("title: T\n1 | T1 | hook | 2\n3 | T3 | h\n") == {1: 1}
```

`parse_draft` keeps returning `(title, items)`; its `split("|", 2)` becomes `split("|", 3)` with the hook taken from `parts[2]` and a 4th field ignored there. `parse_choices(text) -> dict[int, int]` maps id → 0-based choice from the optional 4th field (1-based in the file); lines without it are left out.

TUI (`tests/tui/test_build_kinds.py`, same helpers as `tests/tui/test_build_chapter.py`):

```python
import pytest

pytest.importorskip("textual")

from manhwatok.domain.models import PostKind  # noqa: E402
from manhwatok.tui.screens.build import BuildPane  # noqa: E402
from tests.tui.helpers import make_ctx, run_app  # noqa: E402


def _shown(pane, widget_id) -> bool:
    return pane.query_one(f"#{widget_id}").display  # copy test_build_chapter.py's _shown if it differs


@pytest.mark.parametrize("kind", ["similar", "versus", "guess", "characters"])
def test_each_kind_uses_the_list_form(tmp_path, kind):
    ctx = make_ctx(tmp_path)

    async def scenario(app, pilot):
        await pilot.press("2")
        await pilot.pause()
        pane = app.query_one(BuildPane)
        pane.query_one(f"#mode-{kind}").value = True
        await pilot.pause()
        assert pane.kind is PostKind(kind)
        assert _shown(pane, "search") and not _shown(pane, "chapter-build")
        assert _shown(pane, "like") is (kind == "similar")

    run_app(ctx, scenario)
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3: implement.**
- `build`: `kind: PostKind = typer.Option(PostKind.LIST, "--kind", help="list, versus, guess or characters (use --like for if-you-liked, `chapter build` for chapters)")`, `like: Optional[str] = typer.Option(None, "--like", help="Build an 'if you liked' post from this title's AniList recommendations.")`. `--like` → `seed = resolve_title(like, tools.metadata)`, `find = lambda: similar_candidates(seed, acct, ...)`, `title = title or similar_title(seed)`, `kind = SIMILAR`. Refuse `--kind chapter` with a pointer to `chapter build`. Pass `kind`, `seed` into `build_post`.
- `build_post`: after `parse_draft`, if `kind is CHARACTERS`: `items = with_characters(items, tools.metadata, parse_choices(text))` (error → saved as an unfinished draft, like other draft errors). `render_draft` for characters adds a help line `# characters: add "| N" to a line to rank its Nth character (default 1)` and lists each candidate's character names in a comment when `tools.metadata` is available (one `character_choices` call).
- TUI `BuildPane`: radio buttons `mode-list`, `mode-similar`, `mode-versus`, `mode-guess`, `mode-characters`, `mode-chapter`; `on_radio_set_changed` sets `self.kind = PostKind(pressed.id.removeprefix("mode-"))` and toggles class `-chapter` only for chapter (list widgets serve every other kind); add a "Like" `Input(id="like")` shown only in similar mode (class `similar`, CSS hidden unless `-similar`). Search in similar mode runs `similar_candidates`; the save callback passes `kind=self.kind, seed=...`; for characters, `PicksScreen` rows get a `Select` of character names (from one `character_choices` call) and the callback applies `with_characters` with the chosen indexes.

- [ ] **Step 4:** `uv run pytest -q` → PASS.
- [ ] **Step 5:** commit `feat(cli,tui): build every post kind`.

---

### Task 9: README + real-world check

**Files:** Modify `README.md` (new section "Post kinds" after "Cover versions": one paragraph per kind, the CLI lines, the web tabs).

- [ ] **Step 1:** write the section:

```markdown
## Post kinds

Besides recommendation lists and chapters, a post can be:

- **If you liked X** (`build --like "Title"`, web tab *If you liked*) — the title's AniList
  recommendations, minus what the account blocks or posted recently, as a normal list.
- **Versus** (`build --kind versus`) — picks in pairs, one slide per pair (top vs bottom with a
  VS badge); the end slide asks which wins. Needs an even number of picks.
- **Guess the manhwa** (`build --kind guess`) — per title a clue (a tight crop of its art, the
  genres, year and status) then the reveal. Up to 16 titles; the caption hides the answers
  below the fold.
- **Character ranking** (`build --kind characters`) — one of each pick's top characters (web:
  choose in the picks list; draft: add `| N` to a line), ranked by name with the title as the
  label.

Every kind uses the list covers; the pill says what the post holds (IF YOU LIKED, 3 ROUNDS,
GUESS 10, TOP 5).
```

- [ ] **Step 2:** in a scratch data dir (`MANHWATOK_DATA_DIR=<scratchpad>/data`, copy of the real one), build one post per kind for an account through the web UI, render, montage cover + first two middle slides + end, review; fix what reads badly.
- [ ] **Step 3:** `uv run pytest -q` → PASS; commit `docs: post kinds`.
