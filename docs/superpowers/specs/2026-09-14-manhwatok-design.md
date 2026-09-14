# manhwatok: themed manhwa recommendation slideshows for multiple TikTok accounts

## Context
User wants a system to run several TikTok accounts posting manhwa content, modeled on
@manhwaztheguy: pick a theme ("MC regresses for revenge"), find the best matching manhwa,
show cover + chapter count + hook. New standalone project (not part of `minutes`).

Decisions made with user:
- Output: **photo slideshow** (carousel), not video, for v1.
- Publishing: **drafts to TikTok inbox** via official Content Posting API (user taps publish
  in-app and adds a sound). No app audit needed.
- Curation: **auto-suggest from AniList, user approves**/reorders/edits hooks.
- Interface: **CLI + Textual TUI**, same stack/style as `minutes`.
- Accounts: one account can mix **multiple genres**; account model has a `kind` field so other
  profile types can be added later.
- Covers: **template-rendered** with Pillow for every post, per-account style.
- Hosting: **no domain yet**, so v1 ships local export; R2 + TikTok drafts plug in later.

Explicitly out of scope (declined): ingesting/splitting/posting manhwa chapter pages,
reposting others' TikToks, unofficial upload bots / antidetect / proxy ban-evasion.
A future `recap` profile kind (user-chosen panels + commentary) is allowed by the model but not built.

## Location & stack
`~/Documents/Personal/manhwatok` (new git repo). Mirror `minutes` conventions
(`pyproject.toml`: uv_build, Python ≥3.12, typer, textual, pydantic, httpx, pytest;
layout `src/manhwatok/{domain,ports,adapters,app,tui}` ports-and-adapters like
`src/minutes/`). New deps: `pillow`, `pyyaml`. Later: `boto3` (R2).

## Design

### Domain (`domain/`)
- `Manhwa`: anilist_id, title (english/romaji), status, chapters (nullable), latest_chapter,
  genres, tags, score, popularity, cover_url, description.
- `AccountProfile`: handle, kind (`recommendation`; enum open for later), genres/tags it covers,
  hashtags, caption template, style (palette, font, accent color).
- `ListPost`: id, account, theme title, ordered `PostItem`s (manhwa + hook text), caption, status
  (`draft` → `rendered` → `exported`/`sent`).
- Pure helpers: chapter label ("145 chapters · completed" / "ongoing · ch. 212"),
  caption+hashtag assembly, dedupe filter (exclude titles the account posted in last N days).

### Ports (`ports/`)
`MetadataSource`, `SlideRenderer`, `ImageHost`, `Publisher`, `Store`.

### Adapters (`adapters/`)
- `anilist.py`: GraphQL `https://graphql.anilist.co`. Query `Page(media: type MANGA,
  countryOfOrigin: KR, genre_in, tag_in, sort SCORE_DESC|POPULARITY_DESC)`, fields chapters, status,
  coverImage.extraLarge, averageScore, popularity, description. Also a tag-list query for `manhwatok tags`.
  Respect 90 req/min rate limit, cache responses in store.
- `mangaupdates.py`: fills `latest_chapter` for ongoing series where AniList `chapters` is null
  (`api.mangaupdates.com/v1/series/search`).
- `pillow_renderer.py`: 1080×1920 PNGs (size configurable).
  - Cover slide: blurred collage of the listed covers + big theme title, account colors.
  - Item slide: cover art, rank number, title, chapter label, hook (auto-wrapped, shrink-to-fit).
  - End slide: CTA ("which one have you read? follow for more").
  - Bundled OFL fonts (e.g. Anton + Inter) in `assets/fonts`.
- `local_export.py` (Publisher, v1 default): `out/<account>/<post-id>/01.png…`, `caption.txt`.
- `sqlite_store.py`: accounts, posts, post history, AniList cache (stdlib `sqlite3`).
- Later (Phase 4): `r2_host.py` (S3 API upload → public URL on verified subdomain) and
  `tiktok_drafts.py`: OAuth (Login Kit, scope `video.upload`), per-account tokens with refresh,
  `POST /v2/post/publish/content/init/` with `media_type=PHOTO`, `post_mode=MEDIA_UPLOAD`,
  `source_info.source=PULL_FROM_URL`, `photo_images=[urls]`, `photo_cover_index=0`; poll status.

### App use cases (`app/`)
`SuggestTitles(theme/tags, account, n)` → ranked candidates minus recent history ·
`BuildPost(account, theme, picks, hooks)` · `RenderPost(post_id)` · `PublishPost(post_id)`
(routes to whichever Publisher is configured).
Hook prefill = first sentence of AniList description (HTML stripped), user edits.

### CLI (`cli.py`, typer) and TUI (`tui/`)
```
manhwatok account add @handle --genres Action,Fantasy --hashtags "#manhwa #manhwarec"
manhwatok tags                          # list AniList tags
manhwatok theme add regression-revenge --tags "Time Manipulation,Revenge" --title "MANHWA WHERE THE MC REGRESSES FOR REVENGE"
manhwatok suggest regression-revenge --account @handle -n 12
manhwatok build / render <post-id> / publish <post-id>
manhwatok tui
```
TUI: pick account → pick theme → candidate list (toggle, reorder, edit hook) → render →
open preview → export/send.

## Phases
1. Scaffold repo, domain, AniList + MangaUpdates adapters, store, `suggest` + `tags` CLI.
2. Pillow renderer (cover/item/end slides) + local export + `build/render/publish`.
3. Account profiles, themes, history dedupe, Textual TUI.
4. (Once a domain exists) R2 host + TikTok developer app (sandbox first) + drafts publisher.

Each phase gets its own task-level implementation plan under `docs/superpowers/plans/`, built TDD.

## Open details (decided during implementation, not blocking)
- Theme presets live in the SQLite store (`theme add`), not YAML; `pyyaml` dropped unless needed.
- Slide size default 1080×1920; safe area = 90 px side margins, 250 px top/bottom (TikTok UI overlays).

## Carry-forward from Phase 1 review (address in the named phase's plan)
- Phase 2: AniList adapter drops spoiler tags and tag ranks (`Manhwa.tags` is names only). Add a
  `Tag(name, rank, spoiler)` model if ranking/"why it matched" needs it.
- Phase 2/3: history dedupe needs over-fetching — `search()` is `page: 1, perPage: limit`, so
  filtering posted titles afterwards returns fewer than `n`; request `limit + excluded` (≤50) or add paging.
- Phase 3: account genres are OR but AniList `genre_in` is AND → one query per genre; then cache
  AniList search responses (90 req/min limit).
- Phase 3 (prerequisite for TUI workers): `SqliteCache` never closes its connection and uses the
  default `check_same_thread=True`; give one owner the DB connection + schema versioning
  (`PRAGMA user_version`) when `sqlite_store.py` lands, and turn `container` build functions into a
  lifecycle-owning container built on the thread that uses it.
- Cosmetic: CLI usage errors exit 1 (not click's 2).

## Carry-forward from Phase 2 review (address in the named phase's plan)
- Phase 3: split `build_post` into a pure `create_post(candidates, title, items, hashtags, accent, now)`
  shared by the draft-file CLI and the TUI (the `EditorFn` contract doesn't fit a Textual screen);
  this also removes the build/edit "parse → save draft → re-raise" duplication.
- Phase 3: introduce a `SlideStyle` (fonts, sizes, accent, CTA texts `END_TITLE`/`FOLLOW`) passed into
  `layout_*` and `PillowRenderer` before per-account styles land.
- Phase 3: extend `ListPost` with defaulted `account`, `status` (draft → rendered → exported/sent) and
  maybe `schema_version` so existing `post.json` files keep loading; decide whether posts stay
  folder-only (history dedupe scans every `post.json`) or get indexed in the SQLite store.
- Phase 3: fold `CoverCache`'s `httpx.Client` into the lifecycle-owning container; let `export`/`posts`
  get the repository without building the whole `PostTools`. Reserve post ids with
  `mkdir(exist_ok=False)` (`new_id` has a check-then-act race once TUI workers exist).
- Phase 3: `manhwatok delete <id>` (cancelled/abandoned posts pile up).
- Phase 3 polish: re-download a cached cover that Pillow can't decode (today it silently renders
  the plain fallback forever); blur the end-slide 2×2 grid once (seams at x=540/y=960) and centre
  short recap lists; strip or warn on glyphs Anton/Inter lack (Hangul/CJK/emoji) in hooks.
- Phase 4: verify which image formats TikTok's Content Posting API accepts for photo posts (reviewer
  recalls JPEG/WebP only, not PNG) — add a format option to `render` or convert on upload.

## Verification
- Unit: domain helpers (chapter label, dedupe, caption); AniList/MangaUpdates adapters against
  recorded JSON fixtures; renderer (slide count, 1080×1920, text bbox fits inside safe area);
  use cases with fake ports; TikTok publisher with `httpx.MockTransport` (Phase 4).
- Live: `manhwatok suggest` against real AniList returns KR manhwa with covers; render one post
  and view the PNGs; `publish` produces the export folder with caption.txt. Phase 4: send a
  draft to a sandbox account and confirm it lands in the TikTok inbox.
