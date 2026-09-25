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
`--art none|background|panel|character|scene|quad` (see below); all three default to the account's
(see below). Manhwa
slides take their accent colour from each cover.
Export folder: `--out DIR` or `MANHWATOK_EXPORT_DIR`. Upload the PNGs as a TikTok photo post and
paste `caption.txt` — or let `manhwatok upload` fill them in for you (see below).

```bash
uv run manhwatok delete <id>           # asks first; --yes skips the question
uv run manhwatok chapter build "The Boxer"   # a chapter post, not a list (see below)
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
- `scene` — one picture filling the whole slide, edge to edge and square-cornered, with the text
  over it on a taller scrim. Built for art you picked yourself (see below): a scene is chosen for
  its scale, and every other style shrinks it to a card. Pair it with
  `--source pins --order portrait`.
- `quad` — four of the title's own pictures, 2×2 over the whole slide, text over them. On its
  own, a title's most favourited characters fill the squares and Pinterest scenes fill whatever
  they leave. Name a search and its scenes take all four squares instead, characters standing in
  only where it finds too few:
  `render <id> --art quad --source pins --tag "fight scene"`. Scenes are kept in the post's
  folder as `scene-<id>-<n>` and lead the grid, so a later plain render keeps them and downloads
  nothing; `--replace` searches again. Scenes are taken most-liked first, skipping wide pictures
  and any with words on them (see below). Posts built before this style existed kept only one
  character per title; the first quad render looks up the rest on AniList.

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
| `scene` | your own art (`manhwatok art`) | — | the cover, cropped to fill the slide |
| `quad` | characters, then scenes | characters as above; a title has 0–4 | the cover, then repeats |

Character images are small (about 230×345 against a 460×650 cover), but manhwa art is flat and
clean-lined, so it holds up scaled into a slide. Extra images are cached next to the covers in
`$XDG_DATA_HOME/manhwatok/covers/` and downloaded only when a post's style asks for them.

## Cover versions

Every render draws the cover slide three ways and keeps all three next to the slides:

- `cover-fan.png` (default) — the first three covers fanned out. The original look.
- `cover-quad.png` — the first four titles' characters, one per quadrant, edge to edge. A title
  without a character image gives its picked art or its cover; fewer than four titles repeat.
- `cover-hero.png` — the first title's picked art (else its cover) filling the whole slide.

The chosen one is also `01.png`, the slide that gets exported. An account's post carries a mark
under the progress bar on every version: `@handle`, or whatever the account's `--byline` says.

```bash
uv run manhwatok account set @manhwa.daily --byline "manhwa daily · @manhwa.daily"
uv run manhwatok account set @manhwa.daily --byline ""    # back to "@manhwa.daily"
```

A post keeps the byline it was built with, the way it keeps its end-slide texts, so changing an
account's byline shows on its next posts rather than rewriting the ones already rendered.

```bash
uv run manhwatok cover <id>              # list the versions and which one is current
uv run manhwatok cover <id> quad         # swap it into 01.png, no re-render needed
uv run manhwatok render <id> --cover hero   # or choose while rendering
```

The characters for the quad cover are fetched for the first four titles whatever `--art` is.

## Publishing chapters

A different kind of post: the chapter itself, cut into slides, a part at a time.

```bash
uv run manhwatok chapter list "The Boxer"      # its chapters, and what you've built of them
uv run manhwatok chapter next "The Boxer"      # what `build` would make next
uv run manhwatok chapter build "The Boxer" -a @manhwa.daily
uv run manhwatok chapter build "The Boxer" --number 13 --part 2
```

`build` downloads the chapter's pages, joins them into the one long strip a
webtoon really is, and cuts it into 1080×1920 slides. The cut goes in the lowest gutter within
reach of a full slide, looking as far as half a slide up, and a short slide is padded with the
page's own margin colour. Only when there is no gutter at all does it cut through the art: the
slide is then kept full, like a crop, and the cut raised just enough to clear any speech bubble
or lettering (found by shape, and by RapidOCR's text detector for bubbles with no closed
outline) — never a short slide padded out to hide the cut. Long empty stretches are shortened
and blank slides dropped. The first and last five slides are read with RapidOCR for what is not
the story: scanlator credits, website banners and Discord ads, the title card, "To be
continued" and the end card under it. Such a slide is dropped, or cut back to the gutter above
the junk when the last story panel shares it; the first 25 are also searched for a title card
after a cold open, dropped only when the slide is the title card and nothing else. A chapter is
far more than TikTok's 35 images, so it becomes several posts: chapter 12 of The Boxer is 27 slides of part 1 and 27 of part 2. The cover names
the chapter and the part, and every slide is signed like any other post's. The end slide reads
the title, then what just ended ("Chapter 12 done", "Part 2 next"), then what to follow for
("Follow for part 3", or "Follow for chapter 13" once the last part is out) — worked out from
the chapter itself, so `--cta-title` and `--cta-follow` only shape a recommendation post.

From there it is an ordinary post: `render`, `export`, `upload`, `posts` and the terminal app
all treat it the same. What it isn't is a list of picks, so `edit`, `art` and `cover` say so
rather than opening.

What is tracked per title, in the database: which chapters exist and how many pages each has,
which were downloaded, which parts were built into which post, and when that post went out. So
`build` with no `--number` continues where the last one stopped, and deleting a post frees its
part to be built again.

| | |
| --- | --- |
| Pages | `$XDG_DATA_HOME/manhwatok/pages/<chapter id>/`, with the cut panels beside them |
| Size | 30–100 MB a chapter, and about as much again in panels |
| Re-cutting | a chapter's cut is kept, so later parts split the same way; one cut by an older version of the cutter is cut again on the next `build` (posts already built keep their own copies) |
| Sources | `mangadex` (fan translations, wide catalogue), `webtoons` (the publisher's own English from episode 1, free episodes only) and `asura` (Asura's own translations, whole runs) |
| Language | English only; a title the source has with nothing in English says so |
| Gaps | `chapter list` says where the English run starts, what is missing inside it, and which languages have the rest |
| Speed | about 20s to download a chapter, and 10–30s to cut it |

### Where the pages come from

MangaDex carries what fan groups translated, which for a licensed title is often the middle of
the run: it has The Boxer from chapter 12, and nothing before it. WEBTOON carries the
publisher's own English from episode 1 — but only the free episodes, so a completed or licensed
series may be a short preview (The Boxer: 7) and an ongoing one stops before its Fast Pass
episodes.

```bash
uv run manhwatok chapter list "The Boxer" --source webtoons    # episode 1 onwards
uv run manhwatok chapter build "The Boxer" --source webtoons
```

Without `--source`, a title uses whichever source it is already tracked under, else the first
that has it (MangaDex, then WEBTOON). **A title keeps its source**: chapter 12 does not mean the
same thing in two catalogues, so what has been built and posted is counted per source.

Asura translates ongoing action manhwa itself and keeps the whole run of what it picks up,
which is where it beats both: Solo Leveling is 201 chapters from 0 there against MangaDex's 24,
and Return of the Mad Demon 215 from 1 against MangaDex's 1. Its newest chapters are early
access — paid — and those are left out rather than downloaded empty. It has changed domain four
times (asurascans.com → asura.gg → asuracomic.net → asurascans.com), so the day it moves again,
the host at the top of `adapters/asura.py` is the line to change.

```bash
uv run manhwatok chapter list "Solo Leveling" --source asura
uv run manhwatok chapter build "Solo Leveling" --source asura
```

Sampled over eight of the titles in these posts, WEBTOON had three. None of the three sources
covers everything: MangaDex has the widest catalogue, WEBTOON the official text, Asura the
complete early runs of what it translates.

**Whether you may repost a chapter is your call.** MangaDex hosts fan translations, most of them
unauthorised copies of a licensed work; copyright holders do have TikTok accounts taken down.
The tool says this once in `manhwatok chapter --help` and does what you ask.

Of the titles in a typical themed post, expect roughly a quarter to have English chapters at
all — several have one or two, a few (THE BREAKER - NEW WAVES, Raeliana, Out of Control) have
dozens. `chapter list` tells you before you commit to a title.

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

`--source pins` searches Pinterest, keeping only pins that name the title (see below):

```bash
uv sync --extra pinterest --extra upload --extra tui       # once: gallery-dl
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

There is also no id to pair a title on, only what pins say about themselves, so a title whose
name is an ordinary phrase ("The Boxer") can still collect whatever else shares it. Look at what
you pick before you post it.

### Most-upvoted panels from Reddit

Each manhwa's subreddit has "favourite panel" threads, and upvotes rank them — the closest thing
there is to a community vote on a title's best picture. `--source reddit` searches every
subreddit for posts naming the title (quoted) plus `panel`, most-upvoted of all time first, and
offers the pictures among them.

```bash
uv run manhwatok art <id> 105398 --list --source reddit
uv run manhwatok render <id> --art scene --source reddit --order portrait
uv run manhwatok render <id> --source reddit --tag "best panel" --replace
```

It reads Reddit's public search feed (`search.rss`), the one door Reddit still leaves open to a
plain request — its JSON answers anonymous clients with 403, and its pages answer an automated
browser with a CAPTCHA, which manhwatok does not try to get past. What that costs:

- **Slow.** Reddit allows about one search a minute, so filling a 12-title post takes ~12
  minutes. It waits on its own; if Reddit still says too many requests, it stops and says so.
- **No votes or sizes.** The feed gives the top-voted order but not the numbers, so options show
  their rank (`top #1  r/sololeveling  ...`) and `--order portrait/size` can't re-rank them.
- **Single pictures only.** Gallery posts link to a page rather than their pictures, and are
  skipped.
- **NSFW** is left out by the search itself (`include_over_18=off`); the feed doesn't mark posts.

This is reading Reddit without its permission — against its terms, like the Pinterest search. At
one search a minute it stays well within what Reddit tolerates, but it can stop working whenever
Reddit changes the feed.

If Reddit ever approves an API app for you ([Responsible Builder
Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)),
set `MANHWATOK_REDDIT_CLIENT_ID`, `MANHWATOK_REDDIT_CLIENT_SECRET` and `MANHWATOK_REDDIT_USER`
and the same source uses the API instead: real vote counts, sizes, and gallery pictures.

### Asking for a kind of picture

Pinterest's search is a loose text match, and extra words make it looser: for
"Log-in Murim manhwa fight scene" its top pins were Lookism and Northern Blade art. So
`--source pins` searches the title with `webtoon` alongside it, and keeps a pin only when the
pin's own texts name the manhwa — its title, description, board, alt text, or the labels
Pinterest's image recognition gave it — by the English title, the romanized one, or any of
AniList's alternative titles. Pins that name something else, or nothing, are left out.

Measured over six murim and action titles, 80 pins each, counting pins that name the title:
`<title> webtoon` found the most (e.g. 62 for Return of the Mad Demon), `<title> manhwa` a
little fewer, and `<title> manhwa fight scene` a third as many (11). A title better known under
another name is searched again under that one when the first search names it too rarely:
Log-in Murim is "Murim Login" on Pinterest, 0 pins under the one and 61 under the other.

Posts built before this kept no alternative titles; the first search looks them up on AniList
and saves them into the post.

Pins that have **words on them** are passed over: speech bubbles, meme captions, tweet
screenshots, posters, fake magazine covers. The picture itself is read with RapidOCR (offline,
~0.1s a picture), and a word only counts when it is recognised with
confidence, since text detection alone boxes hair and fabric on detailed art. Checked by hand
against 80 of Pinterest's most-liked pins for four titles, it caught every bubble, caption,
tweet, poster and collage and kept every clean picture, letting artists' @handles and small
corner logos through. Two things it cannot catch: an **empty** bubble has no text to read, and
Korean sound effects drawn into the art usually read as nothing. Without the extra installed,
pictures are not read and the render says so once.

Pins are also compared by what they look like, not only byte for byte, so the same picture
repinned at another size is not used twice in a post.

```bash
uv run manhwatok art <id> 72579 --list --source pins                   # "<title> webtoon"
uv run manhwatok art <id> 72579 --list --source pins --tag "wallpaper"   # "<title> wallpaper"
uv run manhwatok art <id> 72579 --list --source pins --tag ""            # just the title
```

`--order portrait` puts the pins closest to a slide's 9:16 first, which is what `--art scene`
wants: that style crops one picture to fill the whole slide, so a near-portrait pin loses least.

To do it for every title at once, give `render` the same search. Each title gets its first
picture (or `--pick N`'s), and titles you already picked art for keep it unless `--replace`:

```bash
uv run manhwatok render <id> --art scene --source pins --order portrait
uv run manhwatok render <id> --source pins --tag "wallpaper" --pick 2 --replace
```

No two titles in a post get the same picture: fan art often names several titles at once, so
two titles' first result can be the same pin. A title passes over any picture
another title already has — same address, or same file under another address — and takes the
next. A title with nothing found, or whose pictures won't download, keeps its style's own art. Fix it
afterwards with `manhwatok art <id> <anilist-id> --list ...` — the next fill leaves it alone.

`--tag` replaces the default rather than adding to it, and `--tag ""` searches the bare title.

`--order` then rearranges whatever came back:

```bash
uv run manhwatok art <id> 72579 --list --source pins --order portrait
```

- `relevance` (the default) — the source's own order: Pinterest's ranking, a booru's score,
  MangaDex's volume numbers. Leave it alone when the words did the work.
- `popular` — most liked on Pinterest first (the default for `--art quad`), which is as close as
  Pinterest comes to saying which picture stands for the title. The other sources report no
  likes, so there it changes nothing.
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
Themes (tags/genres + title, and the sounds that suit them) are shared by every account.

```bash
uv run manhwatok account add @manhwa.daily --genres Action,Fantasy --block-genres Romance \
    --block-tags Harem --hashtags "#manhwa #manhwarec" --accent "#ff5a5f"
uv run manhwatok account set @manhwa.daily --cta-follow "Follow for more"   # only these change
uv run manhwatok account list                     # also: show <handle>, remove <handle>

uv run manhwatok theme add regression-revenge -t "Time Manipulation" -t Revenge \
    --title "Manhwa where the MC *regresses* for *revenge*"
uv run manhwatok theme set regression-revenge --sound "Close Eyes DVRST"   # only these change
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
  protection. `--cta-title` / `--cta-follow` set a recommendation post's end-slide texts
  (`*word*` = accent colour); a chapter post's last slide says what its chapter needs instead.

## Next post

An account can keep a rotation of what it posts, and `next` makes its next post from it without
asking anything: built, art filled and rendered, ready for you to look over before it goes out.

```bash
uv run manhwatok account set @manhwa.daily \
    --rotation "chapter:Solo Leveling,theme:regression-revenge,theme:isekai" \
    --art-source pins --timezone Europe/Paris
uv run manhwatok next -a @manhwa.daily              # the next item's post
uv run manhwatok next -a @manhwa.daily --count 3    # the next three, in turn
```

- `chapter:<title>` (a title or its AniList id) builds the title's next part, as `chapter build
  --account` does. When every listed chapter is built, the source is asked for new ones first;
  if there are none, `next` warns and moves on to the following item (and gives up after one
  full turn with nothing to make).
- `theme:<name>` builds a list post from a saved theme for the account, as `build --account
  --theme` does, keeping the picks and hooks the editor would open with. With `--art-source`
  (covers, fanart, pins or reddit) every title then gets a picture from there, as `render
  --source` gives it; without, each art style draws its own.
- Items are taken in order and the rotation starts over after the last; repeat an item to post
  it more often. The account remembers its place, and moves on only once a post is made, so a
  failure tries the same item again next time. Setting `--rotation` starts it over; `account
  show` prints it with the item that comes next.
- `next` prints each post's id; check it in `manhwatok tui`, or with `edit <id>` and `render
  <id>` (`render --source ... --replace` picks the art again), then `export` or `upload` it.
- `--timezone` (default `Europe/Paris`) is the account's time zone, for posting times.

## Posting plan

Give an account weekly slots, and `plan fill` makes a post for every slot of the days ahead
from its rotation, as `next` makes them, and schedules each one there.

```bash
uv run manhwatok account set @manhwa.daily --slots "mon 19:00,thu 19:00,daily 12:30"
uv run manhwatok plan fill -a @manhwa.daily          # the next 7 days
uv run manhwatok plan fill --days 10                 # every account with slots, 10 days ahead
uv run manhwatok plan show                           # the week ahead, by day
uv run manhwatok schedule 20260922-a3f9 "thu 19:00"  # one post, by hand
uv run manhwatok schedule 20260922-a3f9 --clear
```

- A slot is `<day> HH:MM`, with the day `mon`…`sun` or `daily`, in the account's `--timezone`.
  `--slots ""` clears them; `account show` lists them. A slot inside the hour the clocks skip in
  spring (02:30 on the last Sunday of March in Paris) goes out an hour later, at 03:30; one
  inside the hour they repeat in autumn goes out on its first pass.
- `plan fill` only fills slots nothing is scheduled at yet, so running it twice makes nothing
  new, and a post you've sent keeps its slot. It looks 7 days ahead by default and 10 at most,
  as far as TikTok schedules. It stops at the first post it can't make (a rotation with nothing
  left, say); the ones made before stay made and scheduled.
- `plan show` lists each slot with its post's id, title and state (not rendered, rendered,
  exported, sent), or `— empty`, in the account's time zone. `-a` shows one account, `--days`
  looks further. A post scheduled at a time that isn't one of its account's slots is listed
  too, marked `(not a slot)`.
- `schedule <id> <when>` takes `YYYY-MM-DD HH:MM` or `<day> HH:MM` (the next such time), in the
  post's account's time zone (`Europe/Paris` for a post without one); `--clear` unschedules it.
  `posts` shows each scheduled post's time (in this computer's time zone).
- The plan is yours to follow: nothing is uploaded at its time. Run `upload <id>` when you are
  ready and it fills the post's slot into TikTok's own schedule, so TikTok posts it then (see
  below). You still click the button.

## Uploading to TikTok (assisted)

`upload` takes the manual steps out of posting but leaves the decision to you: it opens a real,
visible Google Chrome window logged in as the post's account, attaches the slides in order, types
the title and description, adds a sound and — for a post planned for later — fills in TikTok's
own schedule. You check the post (pick the cover) and click **Post** (or **Schedule**) yourself.

```bash
uv sync --extra upload                    # once: Playwright (uses your installed Google Chrome)

uv run manhwatok login @manhwa.daily      # once per account: log in by hand, then quit Chrome (⌘Q / Ctrl+Q)
uv run manhwatok account set @manhwa.daily --emojis "🔥📚" \
  --sound "SOLO LEVELING RaijinLofi" --sound "Dark Aria SawanoHiroyuki"   # optional
uv run manhwatok upload <id>              # an account's post with up-to-date slides
uv run manhwatok upload <id> --at "2026-09-24 19:00"   # fill TikTok's schedule in with this
uv run manhwatok upload <id> --no-schedule             # post it now, whatever the plan says
uv run manhwatok upload <id> --random-sound            # let chance pick the sound, don't ask
uv run manhwatok upload <id> --visibility friends      # who can see this one (see below)
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
- Each `--sound` is a search in TikTok's sound library. `upload` asks which sound to use
  (Enter: the first, 0: none) and adds the first result TikTok finds.
  `upload --sound "..."` searches for something else; `--no-sound` adds none.
- `account add/set --default-sound "..."` is the one sound to use without asking; a post whose
  theme has exactly one sound uses that one the same way. `upload --ask-sound` brings the
  question back (the default sound is offered first then), and `--default-sound ""` clears it.
- `upload --random-sound` lets chance pick instead of asking — one of the very sounds the
  question would have offered, the post's theme's first and then the account's. The line before
  the browser opens says which:
  `post 20260922-a3f9 → @manhwa.daily, posting now, sound: "SOLO LEVELING RaijinLofi" (picked at random)`.
  `account add/set --random-sound` does it for every upload of an account, and
  `--no-random-sound` stops it. A post with no sound to pick from asks as usual.
- The sound is decided in this order, strongest first: `upload --sound "..."` (a search of your
  own) — it can't be combined with `--no-sound`, which adds no sound at all; then
  `--ask-sound`, which asks whatever else is set; then `--random-sound` or the account's;
  then the account's `--default-sound`, or the one sound of the post's theme; else the
  question. The TUI's Posts and Queue tabs follow the same order.
- Sounds live on themes as well as accounts, so a post is offered what suits it: phonk for a
  murim list, something softer for a romance one. A post remembers the theme it was built from,
  and `upload` offers that theme's sounds first, then the account's (a sound on both is listed
  once). Posts built without a theme, or whose theme has been removed since, are offered the
  account's. Set them with `theme add/set --sound "..."`, repeated for several.

### Who can see a post

TikTok's "Who can see this post" starts on **Everyone**, but the page can open on whatever that
account last chose, so every upload reads the list and puts it back to what the post asks for.
A list already showing it is left alone.

```bash
uv run manhwatok account set @manhwa.daily --visibility friends   # every post of this account
uv run manhwatok visibility 20260922-a3f9 private                 # this one post, from now on
uv run manhwatok visibility 20260922-a3f9 --clear                 # back to the account's choice
uv run manhwatok upload 20260922-a3f9 --visibility private        # this one upload only
```

- The three are `everyone`, `friends` (TikTok's "Friends": the followers you follow back) and
  `private` (its "Only you") — handy for looking a post over where it will be seen before
  showing it to anyone.
- **Precedence: `upload --visibility` beats the post's own choice, which beats the account's
  `--visibility`, which is `everyone` unless you set it.** `account show` lists it, and
  `upload --visibility` is a one-off: it changes neither the post nor the account.
- `visibility <id> <who>` sticks to the post, so every upload of it — from the terminal, the
  Posts tab or the Queue — shows it to the same people; `--clear` hands it back to the account.
- The upload says what it is about to do before the browser opens ("post 20260922-a3f9 →
  @manhwa.daily, visible to friends, scheduled for Thu 24 Sep 19:00"), then picks the option in
  TikTok's list and reads the button back. If the button doesn't read what was asked for, that
  is a problem for you to fix in the window — as with the schedule, nothing is assumed.

### TikTok's own schedule

- By default `upload` schedules a post that is planned for later: if its scheduled time (from
  `plan fill` or `schedule`) is between 15 minutes and 10 days away, the browser switches
  TikTok's "When to post" to **Schedule** and fills that date and time in. Anything else is an
  ordinary upload, to go out now. `upload` says which one it is doing before the window opens.
- `--at "YYYY-MM-DD HH:MM"` or `--at "thu 19:00"` (the next such time) schedules another time,
  read in the account's time zone; `--at slot` is the post's own planned time. `--no-schedule`
  posts it now whatever the plan says. A time under 15 minutes or over 10 days away is refused
  before the browser opens — TikTok takes neither.
- TikTok's time picker only has 5-minute steps, so the minute is rounded **down** (19:23 →
  19:20) and `upload` says so. Both boxes are read back afterwards, and anything that doesn't
  match is reported as a problem for you to fix in the window.
- **Scheduling means TikTok saves the slides on its servers** before it posts them, and it asks
  each account to allow that once: "Allow your video to be saved for scheduled posting?".
  manhwatok never clicks Allow for you — the first scheduled upload of an account stops there,
  says so and leaves the window open, with the post unscheduled. Click **Allow** yourself, set
  the time (or run `upload` again), and that account is never asked again.
- manhwatok never clicks **Schedule** either: answer `y` to `Scheduled on @x?` once you have,
  and the post is recorded as sent, with the time TikTok will publish it (`tiktok_scheduled_at`
  in its `post.json`). When the schedule couldn't be set, the question is the usual
  `Posted on @x?` instead, so nothing untrue is recorded.

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
- manhwatok never clicks Post or Schedule (it only fills the schedule's fields in), never
  posts by itself at a planned time and never batch-uploads, and it does nothing to hide that the
  browser is automated. Automating TikTok's website is against TikTok's Terms of Service and may
  trigger captchas or account checks — use it at your own risk.

## Terminal app

```bash
uv sync --extra tui          # once (add --extra upload to keep the upload helper)
uv run manhwatok tui
```

Everything the commands above do, in one window with five tabs (`1`–`5`, `q` quits):

- **Posts** — the list, and a preview of the highlighted post: its slides (`←`/`→` flip, `o`
  opens the slide in your image viewer), the sounds it would be offered, its art style, who
  can see it and emojis (each when set), caption and picks — or, for a chapter post, which chapter and part it is. `e` edit
  picks, `r` render, `a` art, `c` cover version (fan, quad or
  hero; swapped in at once when already rendered), `x` export, `u` upload — filling TikTok's
  schedule from the post's slot and its visibility from the post (else its account), as
  `manhwatok upload` does — (`U` with `--debug`),
  `d` delete, `f` show one account's posts. The scheduled column is when a post goes out, in
  its account's time zone; the sent one is the day it did. `space` marks the post under the
  cursor (`●` in the first column), `ctrl+a` marks every post shown, `esc` clears the marks;
  with marks, `r`, `x` and `U` work through all of them in one run, in the order shown, going
  on past a failure and ending with one summary (`rendered 3, 1 failed: <id> <why>`).
- **Art** (`a` on a post) — the post's titles on the left, with the picture each one is drawn
  with. `enter` on a title lists MangaDex's volume covers for it, `enter` on one of those
  downloads it and re-renders; `s` steps through the sources (covers, fan art, pins), `u` takes
  a file path or URL you type, `c` goes back to the style's own art, `o` opens the current picture
  in your image viewer, `esc` returns.
- **Build** — account, theme or tags/genres, and the post's style: hashtags, accent, emojis and
  art (blank = the account's, shown greyed out); **Search** opens the picks editor: `space`
  picks or drops a title, `shift+↑`/`shift+↓` reorder, `enter` edits a hook, `ctrl+s` saves and
  renders, `esc` cancels. "Find a tag" searches AniList's tags. The **List / Chapter** switch
  at the top turns the form into `chapter build`: pick a title already tracked (or type a new
  one, a name or AniList id), the source (`auto` = the one it is tracked under, else the first
  that has it) and language, and optionally the post title, hashtags, accent and emojis.
  Leave **Chapter** and **Part** blank to carry on where the last post stopped, or name either
  to go back to one: **Check** then says "asked for: chapter 12, part 1 of 3 — built already"
  instead of what comes next, and **Build** makes that very part again.
  **Check** shows what `chapter next` would build ("next: chapter 12, part 2 of 3"), asking
  the source for new chapters when every one on record is built; **Build** downloads, cuts and
  renders that part (page counts show under the buttons) and opens the new post in Posts.
- **Accounts** / **Themes** — `a` add, `e` or `enter` edit, `d` remove; `l` logs an account in
  to TikTok. The account form also edits its emojis (`auto` = from each post's genres), its art
  style (`none`, `background`,
  `panel`, `character` or `scene`; blank = none), its sounds, one line separated by ` | ` (e.g.
  `SOLO LEVELING RaijinLofi | Dark Aria SawanoHiroyuki`; blank = none), the default sound
  uploads use without asking (blank = ask) and whether chance picks one of the sounds instead
  of asking (`yes`/`no`; blank = no, as `account set --random-sound`). The theme form edits its
  sounds the same way, and those are offered before the account's. The posting plan is there
  too: slots (`mon 19:00, daily 12:30`), rotation (`theme:isekai, chapter:Solo Leveling`; a
  changed rotation starts over), time zone, art source and who can see its posts (`everyone`,
  `friends` or `private`; blank = everyone).
- **Queue** — `plan show` for the next 7 days, by day, in each account's time zone: every slot
  with its post (or `empty`), posts scheduled off the slots marked `not a slot`, and posts whose
  time has passed without being sent on top, marked `overdue`. `f` fills the highlighted
  account's empty slots (as `plan fill`), `F` every account's, `enter` opens the post in Posts,
  `m` moves it to another empty slot of its account, `u` uploads it with its slot filled into
  TikTok's schedule (one post at a time, and not while another browser window is open), `x`
  unschedules it (the post is kept), `r` refreshes.

Slides show as real pictures in terminals with image support (kitty, WezTerm, Konsole, foot and
other sixel terminals); elsewhere as coloured blocks. Uploading works as with `manhwatok upload`:
if the account has sounds, a dialog first asks which one to add (or "no sound"; `esc` adds
none) — unless the account picks at random, or a preset sound decides — the log shows what the
browser did, and a dialog asks whether you posted it. A bulk `U` asks the same questions, post
after post, without the log screen. Only one render and one
browser run at a time (a bulk run counts as the render); quitting waits for both. The TUI and the commands can be
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
