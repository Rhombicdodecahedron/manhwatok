# New post kinds: If you liked X, Versus, Guess the manhwa, Character ranking

## Goal
Beyond recommendation lists and chapters, an account can post four more kinds of slideshow, each
built, rendered, captioned, uploaded and counted as posted like a list post, and reachable from
the web (New post tabs), the CLI and the TUI.

| Kind | Slides | Built from |
|------|--------|-----------|
| `similar` — "If you liked X" | cover, one slide per recommendation, end | a seed title → its AniList recommendations |
| `versus` — this or that | cover, one slide per pair (A vs B), end asking for votes | a list search; picks taken in pairs |
| `guess` — guess the manhwa | cover, per title a clue slide then its reveal, end | a list search |
| `characters` — character ranking | cover, one slide per character, end | a list search; each pick's character chosen from its top 4 |

## Model
- `PostKind(StrEnum)`: `list` (default), `chapter`, `similar`, `versus`, `guess`, `characters`.
  `ListPost.kind` defaults to `list`; a validator sets `chapter` when `chapter` is present, so
  every existing post.json loads unchanged. Code that branches on `post.chapter` keeps working;
  new branches use `post.kind`.
- `ListPost.seed: Manhwa | None` — the "if you liked" title (drawn on the cover, kept out of the
  items and out of history).
- `PostItem.character: CharacterPick | None` — `name`, `image_url`, `role` (MAIN/SUPPORTING),
  `favourites`. Only `characters` posts set it.
- `Manhwa.character_names: list[str]` parallel to `character_urls` (AniList `_EXTRAS` and the
  media queries also fetch `name { full }`, `role`, `favourites`). Older titles have none; the
  characters flow fetches extras for them.
- `slide_count`: versus = ceil(items/2) + 2; guess = 2·items + 2; others unchanged.
- Validation (`check_picks` by kind): versus needs an even count ≥ 2 (max 2·17 picks);
  guess ≤ 16 titles (33 slides); characters needs a character on every item.

## AniList
- `MetadataSource.recommendations(anilist_id, limit=20) -> list[Manhwa]`: `Media(id){
  recommendations(sort: RATING_DESC){ nodes { mediaRecommendation { …same fields… } } } }`,
  keeping manga from KR (manhwa) first, then others; the seed itself and blocked genres/tags of
  the account dropped, then the account's history filter, as `suggest_for_account` does.
- `find` is added to the port (the seed is picked by name or AniList id, as the chapter flow's
  `resolve_title` already does).

## Rendering (`adapters/kind_slides.py`, reusing renderer helpers)
- **Covers**: every non-chapter kind draws the 7 list cover versions; only the pill text changes:
  "IF YOU LIKED" (the seed's cover leads fan/hero/number art), "N ROUNDS", "GUESS N", "TOP N".
- **similar** item slides = list item slides. Default title "If you liked *<seed>*".
- **versus** slide: the two titles' best pieces (`_best_piece`) as top and bottom halves split by
  a diagonal accent band with a round "VS" badge in the middle; each half carries its name and
  status pill (top half's text at its bottom, bottom half's above the byline). End slide:
  "Comment *A* or *B*" per round list + follow line.
- **guess** clue slide: the title's best piece zoomed hard (picker focus on character, picked
  art and scenes — the cover only as a last resort, cut clear of its lettering), "GUESS #n"
  big, a hint line (first two genres · start year · status). Reveal slide = the list item slide
  with "#n" as the rank. End slide: the answers recapped, "How many did you get?".
- **characters** slide: the character portrait as the card (as `ArtStyle.CHARACTER`), rank,
  character name as the big text, the title in the pill, hook = the item's hook (defaults to
  "<role> · <title>"). End slide: ranked names.

## Caption
- similar: "If you liked X, read:" then the numbered list.
- versus: "1. A vs B" lines; guess: "Answers: 1. A …" (spoiler below the fold);
  characters: "1. Name (Title)".
- History records every item's title id (both sides of a versus; a character's title).

## Frontend
- **Web `/new`**: tabs List · If you liked · Versus · Guess · Characters · Chapter
  (`?type=<kind>`). Versus/Guess/Characters reuse the list search form and results with a
  hidden `kind`; the picks editor shows pairs for versus ("A vs B" grouping, even-count check)
  and, for characters, a select of the pick's top 4 characters (name + thumbnail) per row.
  If-you-liked has a seed field (tracked-title select or free text) → results → the same picks
  editor. Post detail shows the kind; edit page hides what a kind can't change.
- **CLI**: `build --kind versus|guess|characters`, `build --like "Title"` (similar); the draft
  editor gains a `character:` line per pick for characters.
- **TUI**: the build pane's mode radio gains the kinds (class `-kind-<kind>` instead of
  `-chapter`); the picks screen groups pairs / shows the character choice.

## Out of scope
Changing an existing post's kind; per-kind art styles beyond the list ones; video.

## Testing
Unit: model defaults/validators, recommendations parsing (fixture JSON), check_picks per kind,
slide counts, each kind's slides (pixel checks as the cover tests do), captions, history.
Web/CLI/TUI: each tab builds a post of its kind against fakes. Real-world: build one post of
each kind for an account in a scratch data dir and review the slides.

## Build order (one commit each)
1. model + AniList (recommendations, character names) 2. similar 3. versus 4. guess
5. characters 6. web tabs 7. CLI + TUI 8. README.
