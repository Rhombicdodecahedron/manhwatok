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

Options: `--hashtags "..."` (caption hashtags), `--accent "#43c9e4"` (cover/end slide colour),
`--art none|background` (see below); all three default to the account's (see below). Manhwa
slides take their accent colour from each cover.
Export folder: `--out DIR` or `MANHWATOK_EXPORT_DIR`. Upload the PNGs as a TikTok photo post and
paste `caption.txt` — or let `manhwatok upload` fill them in for you (see below).

```bash
uv run manhwatok delete <id>           # asks first; --yes skips the question
```

## Slide art

`--art` picks what a manhwa slide is built around:

- `none` (default) — the upright cover on its own blurred self. The original look.
- `background` — the same upright cover, on that title's AniList banner art instead. The slide
  takes its mood from the story's art rather than from a cover blurred past recognition.
- `panel` — the banner itself, cropped wide and sharp in place of the cover card, with the
  blurred banner behind it. The most cinematic of the four.
- `character` — the title's most-favourited character in place of the cover, on the usual
  blurred cover. The only art AniList has that carries no title lettering.

```bash
uv run manhwatok build -t Revenge --title "..." --art panel
uv run manhwatok render <id> --art background     # restyle a post you already built
uv run manhwatok account set @manhwa.daily --art panel   # default for new posts
```

Every style falls back to the cover, so a post never renders half-finished:

| Style | Needs | Roughly how often AniList has it | Without it |
| --- | --- | --- | --- |
| `background` | banner | 37–61%, lower on niche tags | the blurred cover, as `none` |
| `panel` | banner | as above | the cover, cropped to the same wide shape |
| `character` | character image | 61–99%, lower on niche tags | the cover card, as `none` |

Character images are small (about 230×345 against a 460×650 cover), but manhwa art is flat and
clean-lined, so it holds up scaled into a slide. Extra images are cached next to the covers in
`$XDG_DATA_HOME/manhwatok/covers/` and downloaded only when a post's style asks for them.

## Your own art for one title

AniList only has what AniList has, and for the long tail that is a cover and nothing else. When
you find something better yourself, hand it to the title directly:

```bash
uv run manhwatok art <id> 128067 https://example.com/art.jpg   # a link, downloaded for you
uv run manhwatok art <id> 128067 ~/Downloads/pick.png          # or a file you saved
uv run manhwatok art <id> 128067 --clear                       # back to the style's own art
```

`128067` is the title's AniList id, the first field on each line of the draft. A link must point
at the image itself, not the page it sits on — right-click the picture and copy the image
address. Linking a page gets you "it served text/html" rather than a broken slide.

### Volume covers from MangaDex

AniList keeps one cover per title, and it is usually the first volume's. MangaDex normally has
the whole run, so `--list` offers those instead of sending you looking:

```bash
uv run manhwatok art <id> 136220 --list       # what MangaDex has for that title
uv run manhwatok art <id> 136220 --pick 4     # download the 4th and use it
```

The title is matched on the AniList id MangaDex stores against its own records, not on its name,
so it is the right series or none at all. That pairing is cached in the database for 30 days,
since it does not change once made. A title MangaDex doesn't carry simply lists nothing.

These are publisher volume covers, the same kind of art the tool already fetches — not
scanlation pages, which carry the scanlator's watermark and the publisher's copyright.

### Fan art from Danbooru

`--source fanart` asks Danbooru instead, best-scored first:

```bash
uv run manhwatok art <id> 72579 --list --source fanart
uv run manhwatok art <id> 72579 --list --source fanart --pick 1
```

Only art Danbooru rates general or sensitive is offered, never questionable or explicit — the
highest-scored results for a title are routinely explicit, so this filter is not optional. It is
applied here rather than in the search because Danbooru allows only two search terms, and both
go on naming the title and ordering the results. Each
option shows its score, size and artist, because this is art by individual people rather than a
publisher: `★ 5  1260x1443  by nrynstr`.

`--tag` narrows the search to art also described that way:

```bash
uv run manhwatok art <id> 72579 --list --source fanart --tag solo
```

Danbooru allows two search terms, so a tag costs the score ordering one; the results are ranked
afterwards instead, which comes to the same thing at these list sizes. The vocabulary is
Danbooru's own — `solo`, `full_body`, `upper_body`, `simple_background` and so on, underscored.

Do not expect it to find action shots. What is tagged on this art is overwhelmingly portrait
description — `1girl`, `upper_body`, `solo`, hair and eye colour, jewellery — because that is
what fan artists draw. Live, `--tag solo` narrows Kubera from nine pictures to seven, while
`--tag full_body` and `--tag fighting_stance` both find nothing at all. A panel of the story
happening is not something a booru indexes.

Coverage is thin and skewed to the best-known titles. Of twelve titles tried, five had a tag at
all and only two had more than a couple of pictures; Solo Leveling alone has more than all of
them together. Expect `no fanart found` for most of the long tail — which is exactly the part of
the catalogue this tool exists to surface.

A booru has no AniList id to pair on, only tag names, so a title is matched only when a
*copyright* tag is named exactly after it. Matching loosely finds the wrong series outright —
live, "The Return of the 8th Class Mage" matches a Gundam series and "I Am the Real One" matches
a tag about clothing. Titles filed under another romanisation are missed as a result, which is
the better way to be wrong: nothing beats the wrong series' art on a slide.

### A Pinterest search

`--source pins` searches Pinterest, biggest picture first:

```bash
uv sync --extra pinterest                                   # once: installs gallery-dl
uv run manhwatok art <id> 72579 --list --source pins
uv run manhwatok art <id> 72579 --list --source pins --tag fanart
```

This finds far more than the other two. Long-tail titles with no MangaDex covers and no booru
tag usually have something here, often already at slide proportions — 1080x1920 and 1440x1920
both come back for Kubera.

What it cannot give you is a name. Pinterest records no origin for a pin: the source link is
empty and the domain reads "Uploaded by user" on essentially everything, so no artist is shown
because there is none to show. Most pins are re-uploads of someone's work with the credit
already stripped. On an account that grows, that is the thing to weigh — `--source covers` is
publisher art and carries none of it.

There is also no id to pair a title on, only the words searched, so a title whose name is an
ordinary phrase collects whatever else shares it. Look at what you pick before you post it.

### Asking for a kind of picture

There is no "epic" to sort by — no source scores a picture on what is happening in it. What
there is instead is the search itself, and Pinterest's ranking answers it. `--source pins`
therefore searches for `epic fight scene` alongside the title unless told otherwise, because
that is measurably the best generic phrase: over four titles and 120 pins apiece, the bare title
returned square character portraits (68% near a slide's 9:16) and this returns scene art (75%,
and 97% portrait at usable size).

The word doing the work is "scene", not "epic". Phrases built on it all scored 62-78%, while
`epic`, `epic moment` and `best moment` scored 50-53% — no better than no words at all.
Judgement words describe quality; Pinterest indexes captions, where "scene" describes format.

```bash
uv run manhwatok art <id> 72579 --list --source pins                      # the default phrase
uv run manhwatok art <id> 72579 --list --source pins --tag "fight scene wallpaper"
uv run manhwatok art <id> 72579 --list --source pins --tag ""             # just the title
```

`--tag` replaces the default rather than adding to it, and `--tag ""` searches the bare title.

`--order` then rearranges whatever came back:

```bash
uv run manhwatok art <id> 72579 --list --source pins --tag "epic fight scene" --order portrait
```

- `relevance` (the default) — the source's own order: Pinterest's ranking, a booru's score,
  MangaDex's volume numbers. Leave it alone when the words did the work.
- `portrait` — closest to a slide's 9:16 first. On the search above this brings every 1080x1920
  and 720x1280 to the top.
- `size` — biggest first, when you only care about resolution.

Ordering happens after the search, so `--pick N` always counts down the list `--list` printed.
MangaDex reports no dimensions without downloading, so `--order` leaves its covers alone.

Pinterest has no public search API, so this shells out to `gallery-dl` rather than keeping
scraping code here. Without the extra installed it says so and does nothing.

The picture is copied into the post's folder, so it survives the original moving or being
deleted, and every later `render` and `edit` keeps using it. It beats whatever the post's style
would have fetched, and re-renders the post straight away. The rest of the slide is unchanged:
the backdrop still comes from the style.

Good places to look: AniList and MyAnimeList to pin down who a character actually is, then
Zerochan, Safebooru or Pinterest for art of them. Two things worth knowing before you post it —
those boards are mostly fan art by individual artists, who do notice their work on growing
accounts, and their coverage is thinnest for exactly the small titles this option exists for.
Publisher art (the covers and banners the tool fetches itself) does not carry that risk.

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
visible Google Chrome window logged in as the post's account, attaches the slides in order, types
the title and description and adds a sound. You check the post (pick the cover) and click **Post**
yourself.

```bash
uv sync --extra upload                    # once: Playwright (uses your installed Google Chrome)

uv run manhwatok login @manhwa.daily      # once per account: log in by hand, then quit Chrome (⌘Q / Ctrl+Q)
uv run manhwatok account set @manhwa.daily --emojis "🔥📚" \
  --sound "SOLO LEVELING RaijinLofi" --sound "Dark Aria SawanoHiroyuki"   # optional
uv run manhwatok upload <id>              # an account's post with up-to-date slides
```

- TikTok's title field gets the post title plus the post's emojis (`build --emojis`, default:
  the account's `--emojis`); emojis never go on the slides. The description gets the numbered
  picks and the hashtags, each picked from TikTok's suggestions so it becomes a real hashtag.
- `--emojis auto` (on the account or one post) drops the fixed string: the emojis come from the
  genres its picks share — every genre more than half of them carry, commonest first, up to four
  emojis; with no such genre, the commonest one alone. One account can then run several genres:

  ```bash
  uv run manhwatok account add @manhwa.generic \
    --genres "Action,Fantasy,Romance,Horror" --emojis auto
  ```

  They are worked out when the caption is written, so re-picking a post updates them.
- Each `--sound` is a search in TikTok's sound library. `upload` asks which of the account's
  sounds to use (Enter: the first, 0: none) and adds the first result TikTok finds.
  `upload --sound "..."` searches for something else; `--no-sound` adds none.

- Each account gets its own browser profile in `$XDG_DATA_HOME/manhwatok/browser/<handle>/`;
  manhwatok never sees your password. Captchas and login checks are yours to answer in the
  window.
- `login` opens Chrome on its own, with nothing automating it: TikTok won't finish a login in a
  browser Playwright controls. `upload` then drives Chrome with Playwright on that same profile.
  A profile saved before this change has no login in it — run `login` again.
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

## Terminal app

```bash
uv sync --extra tui          # once (add --extra upload to keep the upload helper)
uv run manhwatok tui
```

Everything the commands above do, in one window with four tabs (`1`–`4`, `q` quits):

- **Posts** — the list, and a preview of the highlighted post: its slides (`←`/`→` flip, `o`
  opens the slide in your image viewer), its account's sounds, its art style and emojis (when
  set), caption and picks. `e` edit picks, `r` render, `a` art, `x` export, `u` upload (`U` with
  `--debug`), `d` delete, `f` show one account's posts.
- **Art** (`a` on a post) — the post's titles on the left, with the picture each one is drawn
  with. `enter` on a title lists MangaDex's volume covers for it, `enter` on one of those
  downloads it and re-renders; `s` steps through the sources (covers, fan art, pins), `u` takes
  a file path or URL you type, `c` goes back to the style's own art, `o` opens the current picture
  in your image viewer, `esc` returns.
- **Build** — account, theme or tags/genres, and the post's style: hashtags, accent, emojis and
  art (blank = the account's, shown greyed out); **Search** opens the picks editor: `space`
  picks or drops a title, `shift+↑`/`shift+↓` reorder, `enter` edits a hook, `ctrl+s` saves and
  renders, `esc` cancels. "Find a tag" searches AniList's tags.
- **Accounts** / **Themes** — `a` add, `e` or `enter` edit, `d` remove; `l` logs an account in
  to TikTok. The account form also edits its emojis (`auto` = from each post's genres), its art
  style (`none`, `background`,
  `panel` or `character`; blank = none) and its sounds, one line separated by ` | ` (e.g.
  `SOLO LEVELING RaijinLofi | Dark Aria SawanoHiroyuki`; blank = none).

Slides show as real pictures in terminals with image support (kitty, WezTerm, Konsole, foot and
other sixel terminals); elsewhere as coloured blocks. Uploading works as with `manhwatok upload`:
if the account has sounds, a dialog first asks which one to add (or "no sound"; `esc` adds
none), the log shows what the browser did, and a dialog asks whether you posted it. Only one
render and one browser run at a time; quitting waits for both. The TUI and the commands can be
used at the same time.

## Upgrading from earlier versions

- The database upgrades itself the first time you run any command; cached chapter counts are
  kept.
- Existing posts show `-` in the `posts` account column and don't count toward any account's
  repeat history.
- Re-rendering an old post (`render`, `edit`) uses the new Montserrat style.
- A post keeps the end-slide texts and art style it was built with: a later `account set
  --cta-title` / `--cta-follow` / `--art` doesn't change existing posts. Use `render <id> --art`
  to restyle one.
- The database switches to WAL mode the first time any command opens it (`manhwatok.db-wal` and
  `manhwatok.db-shm` appear next to it while it's in use).
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
