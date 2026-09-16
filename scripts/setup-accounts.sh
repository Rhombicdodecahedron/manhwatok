#!/usr/bin/env bash
# Sets up the accounts and themes described in docs/accounts.md. Safe to run again: an
# existing account is updated instead of added, an existing theme is left as it is.
# Rename the handles below to your real TikTok handles first.
set -uo pipefail
cd "${MANHWATOK_PROJECT:-$(dirname "$0")/..}"

ACTION=@firstaccount   # action / regression / dungeon
ROMANCE=@secondaccount # romance fantasy / villainess
DARK=""                # thriller / horror / crime — set a handle (e.g. @yourdarkaccount) to enable

mt() { uv run manhwatok "$@"; }

account() {  # account <handle> <options…>: add it, or update it if it already exists
  local handle=$1 out; shift
  if out=$(mt account add "$handle" "$@" 2>&1); then
    echo "$out"
  elif [[ $out == *"already exists"* ]]; then
    mt account set "$handle" "$@"
  else
    echo "$out" >&2
  fi
}

theme() {  # theme <name> <options…>: add it unless it already exists
  local name=$1 out; shift
  if out=$(mt theme add "$name" "$@" 2>&1); then
    echo "theme $name added"
  elif [[ $out == *"already exists"* ]]; then
    echo "theme $name already exists — kept"
  else
    echo "$out" >&2
  fi
}

# --- accounts ------------------------------------------------------------------------------

account "$ACTION" \
  --genres "Action, Fantasy" \
  --block-genres "Hentai, Ecchi" \
  --hashtags "#manhwa #manhwarecommendation #webtoon #manhwatiktok #manhwaedit" \
  --emojis "🔥⚔️" \
  --accent "#e4433c" \
  --art character \
  --cta-title "Which one did you *binge?*" \
  --cta-follow "Follow for part 2" \
  --repeat-days 30 \
  --sound "SOLO LEVELING RaijinLofi" \
  --sound "Dark Aria SawanoHiroyuki" \
  --sound "ReawakeR LiSA" \
  --sound "Murder In My Mind Kordhell" \
  --sound "Metamorphosis INTERWORLD"

account "$ROMANCE" \
  --genres "Romance" \
  --block-genres "Hentai, Ecchi" \
  --hashtags "#manhwa #romancemanhwa #webtoon #villainess #manhwarecommendation" \
  --emojis "👑💕" \
  --accent "#e45da1" \
  --art character \
  --cta-title "Which one stole your *heart?*" \
  --cta-follow "Follow for more romance picks" \
  --repeat-days 30 \
  --sound "Lovely Billie Eilish" \
  --sound "Glimpse of Us Joji" \
  --sound "Die For You The Weeknd" \
  --sound "Sweater Weather The Neighbourhood" \
  --sound "Until I Found You Stephen Sanchez"

if [[ -n "$DARK" ]]; then
  account "$DARK" \
    --genres "Thriller, Psychological, Horror" \
    --block-genres "Hentai, Ecchi" \
    --hashtags "#manhwa #darkmanhwa #webtoon #thriller #manhwarecommendation" \
    --emojis "🩸🖤" \
    --accent "#8b1a1a" \
    --art background \
    --cta-title "Which one gave you *chills?*" \
    --cta-follow "Follow if you like it dark" \
    --repeat-days 45 \
    --sound "After Dark Mr.Kitty" \
    --sound "Close Eyes DVRST" \
    --sound "Sweater Weather The Neighbourhood"
fi

# --- themes (shared by every account) ------------------------------------------------------

# action
theme regression-revenge -t "Time Manipulation" -t Revenge \
  --title "Manhwa where the MC *regresses* for *revenge*"
theme dungeon -t Dungeon -t "Male Protagonist" -g Action \
  --title "Manhwa with *dungeons* you need to read"
theme martial-arts -t "Martial Arts" -g Action \
  --title "*Martial arts* manhwa that go *hard*"
theme necromancer -t Necromancy \
  --title "Manhwa where the MC is a *necromancer*"
theme apocalypse -t Post-Apocalyptic \
  --title "Manhwa set after the *apocalypse*"
theme second-life-mage -t "Age Regression" -t Magic -g Action \
  --title "Manhwa where a *mage* gets a *second life*"

# romance
theme villainess -t Villainess \
  --title "Manhwa where she's the *villainess*"
theme arranged-marriage -t "Arranged Marriage" -g Romance \
  --title "*Arranged marriage* manhwa you'll love"
theme royal-romance -t "Royal Affairs" -t "Female Protagonist" -g Romance \
  --title "Manhwa with *royal* romance"
theme her-second-chance -t "Female Protagonist" -t "Time Manipulation" -g Romance \
  --title "Manhwa where she gets a *second chance*"
theme fake-dating -t "Fake Relationship" -g Romance \
  --title "Manhwa with *fake dating* that turns *real*"

# dark
theme bullied-revenge -t Bullying -t Revenge \
  --title "Manhwa where the *bullied* get *revenge*"
theme gangs -t Gangs \
  --title "*Gang* manhwa you can't put down"
theme zombies -t Zombie \
  --title "*Zombie* manhwa worth your time"
theme crime -t Crime -g Psychological \
  --title "*Psychological* crime manhwa"

echo
mt account list
echo
mt theme list
