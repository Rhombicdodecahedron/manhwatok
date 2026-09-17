# Accounts playbook

Ready-made TikTok accounts for manhwatok: one niche per account, each with its own genres,
hashtags, title emojis, colour, end slide and sounds, plus themes to build posts from.

Set everything up in one go (rename the handles at the top of the script first):

```bash
scripts/setup-accounts.sh
```

It's safe to run again: an existing account gets these settings, an existing theme is kept.
Then log each account in once (quit Chrome with ⌘Q, or Ctrl+Q off a Mac, when TikTok shows you logged in):

```bash
uv run manhwatok login @firstaccount
uv run manhwatok login @secondaccount
```

## The accounts

| | Action (`@firstaccount`) | Romance (`@secondaccount`) | Dark (off until you set a handle) |
|---|---|---|---|
| Niche | regression, dungeons, martial arts | romance fantasy, villainess | thriller, horror, crime |
| Genres (a title needs one) | Action, Fantasy | Romance | Thriller, Psychological, Horror |
| Never | Hentai, Ecchi | Hentai, Ecchi | Hentai, Ecchi |
| Title emojis | 🔥⚔️ | 👑💕 | 🩸🖤 |
| Accent | `#e4433c` red | `#e45da1` pink | `#8b1a1a` blood red |
| Slide art | character | character | background |
| End slide | Which one did you *binge?* / Follow for part 2 | Which one stole your *heart?* / Follow for more romance picks | Which one gave you *chills?* / Follow if you like it dark |
| No repeats for | 30 days | 30 days | 45 days |
| Hashtags | #manhwa #manhwarecommendation #webtoon #manhwatiktok #manhwaedit | #manhwa #romancemanhwa #webtoon #villainess #manhwarecommendation | #manhwa #darkmanhwa #webtoon #thriller #manhwarecommendation |

### Sounds

`upload` asks which of these to use (Enter takes the first). Each one is a search in TikTok's
sound library — the artist's name makes it find the right track. If a search finds the wrong
song, change it with `account set <handle> --sound … --sound …` (that replaces the whole list).

| Action | Romance | Dark |
|---|---|---|
| SOLO LEVELING — RaijinLofi | Lovely — Billie Eilish | After Dark — Mr.Kitty |
| Dark Aria — SawanoHiroyuki | Glimpse of Us — Joji | Close Eyes — DVRST |
| ReawakeR — LiSA | Die For You — The Weeknd | Sweater Weather — The Neighbourhood |
| Murder In My Mind — Kordhell | Sweater Weather — The Neighbourhood | |
| Metamorphosis — INTERWORLD | Until I Found You — Stephen Sanchez | |

## Themes

Every theme below was checked against AniList and finds at least 12 titles. Themes are shared,
so any account can use any of them, but they're grouped by the account they suit.

| Theme | Finds | Post title |
|---|---|---|
| **Action** | | |
| `regression-revenge` | Time Manipulation + Revenge | Manhwa where the MC *regresses* for *revenge* |
| `dungeon` | Dungeon + Male Protagonist, Action | Manhwa with *dungeons* you need to read |
| `martial-arts` | Martial Arts, Action | *Martial arts* manhwa that go *hard* |
| `necromancer` | Necromancy | Manhwa where the MC is a *necromancer* |
| `apocalypse` | Post-Apocalyptic | Manhwa set after the *apocalypse* |
| `second-life-mage` | Age Regression + Magic, Action | Manhwa where a *mage* gets a *second life* |
| **Romance** | | |
| `villainess` | Villainess | Manhwa where she's the *villainess* |
| `arranged-marriage` | Arranged Marriage, Romance | *Arranged marriage* manhwa you'll love |
| `royal-romance` | Royal Affairs + Female Protagonist, Romance | Manhwa with *royal* romance |
| `her-second-chance` | Female Protagonist + Time Manipulation, Romance | Manhwa where she gets a *second chance* |
| `fake-dating` | Fake Relationship, Romance | Manhwa with *fake dating* that turns *real* |
| **Dark** | | |
| `bullied-revenge` | Bullying + Revenge | Manhwa where the *bullied* get *revenge* |
| `gangs` | Gangs | *Gang* manhwa you can't put down |
| `zombies` | Zombie | *Zombie* manhwa worth your time |
| `crime` | Crime, Psychological | *Psychological* crime manhwa |

## Posting

```bash
# build: pick titles and hooks in your editor; prints the post id
uv run manhwatok build -a @firstaccount --theme regression-revenge
uv run manhwatok build -a @secondaccount --theme villainess
uv run manhwatok build -a @firstaccount --theme dungeon --emojis "🗡️🏰"   # emojis for this post only

# upload: pick a sound, check the post in Chrome, click Post, answer y
uv run manhwatok upload <post id>
uv run manhwatok upload <post id> --sound "Another Song Artist"   # a sound not in the list
```

`-a` keeps each account's rules: its genres, its blocks, and no title it posted in the last
30 (or 45) days. Answering `y` after posting is what records those titles.

## Adding another account

Copy one of the `account` blocks in `scripts/setup-accounts.sh`, give it a new handle and
niche, run the script, then `uv run manhwatok login @newhandle`. Tag and genre names must be
AniList's — `uv run manhwatok tags` lists them, and `uv run manhwatok suggest -t … -g …` shows
whether a combination finds enough titles before you make it a theme.
