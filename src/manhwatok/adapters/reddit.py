"""A title's most-upvoted panels on Reddit.

Each manhwa's subreddit keeps "favourite panel" posts, and upvotes rank them — the closest thing
there is to a community vote on a title's best picture. This searches every subreddit for image
posts naming the title, top-voted of all time, and leaves them in that order.

Two ways in, both Reddit's own:

- Without keys, its public search feed (search.rss) — the Atom feed Reddit serves to feed
  readers. It is the one door Reddit still leaves open to a plain request: its JSON answers
  anonymous clients with 403, and its pages answer an automated browser with a CAPTCHA, which
  this deliberately does not try to get past. The feed carries no votes or sizes, only the top
  order, and Reddit allows about one search a minute, which is kept to (see _polite_get).
- With the keys of an app Reddit has approved for you (MANHWATOK_REDDIT_CLIENT_ID / _SECRET /
  _USER), the official API: votes, sizes, galleries, and NSFW posts reliably left out.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path
from typing import Callable

import httpx

from manhwatok.adapters.picture_download import download_picture
from manhwatok.domain.errors import ManhwatokError, MetadataError
from manhwatok.domain.models import Manhwa
from manhwatok.ports.art import ArtOption

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
SEARCH_URL = "https://oauth.reddit.com/search"
FEED_URL = "https://www.reddit.com/search.rss"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
# Direct picture links a feed entry can carry; a gallery or a text post links to a page instead.
PICTURE = re.compile(r'href="(https://(?:i\.redd\.it|i\.imgur\.com)/[\w-]+\.(?:jpe?g|png|webp))"')
# Seconds between feed searches even when Reddit has not asked for more. Measured: two searches
# 30s apart got a 429, while 75s apart never did — its own reset header runs 17-48s, but the
# window behind it is evidently longer.
GAP = 60.0
# Measured: the feed answers 403 to a request asking for gzip/deflate, and 200 to a plain one.
FEED_HEADERS = {"Accept": "application/atom+xml, */*", "Accept-Encoding": "identity"}
MAX_WAIT = 120.0  # the longest a rate-limited search waits before giving up
LIMIT = 100
MIN_SIDE = 600  # a slide is 1080x1920; smaller pictures would be blown up past recognition
# Searched alongside the quoted title unless the caller asks for something else: the "favourite
# panel" threads are what this source is for. Pass "" to search the bare title.
DEFAULT_TAG = "panel"
MIME_EXT = {"image/jpg": "jpg", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
            "image/gif": "gif"}
HINT = (
    "reddit art needs an app Reddit has approved for you (request access under its Responsible "
    "Builder Policy: https://support.reddithelp.com/hc/en-us/articles/42728983564564), then set "
    "MANHWATOK_REDDIT_CLIENT_ID, MANHWATOK_REDDIT_CLIENT_SECRET and MANHWATOK_REDDIT_USER"
)


class RedditSource:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user: str = "",
        client: httpx.Client | None = None,
        timeout: float = 20.0,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        limit: int = LIMIT,
        min_side: int = MIN_SIDE,
        default_tag: str = DEFAULT_TAG,
    ) -> None:
        self._id = client_id
        self._secret = client_secret
        # Reddit's rule for API clients: <platform>:<app id>:<version> (by /u/<username>).
        self._agent = "linux:manhwatok:0.1" + (f" (by /u/{user})" if user else "")
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._clock = clock
        self._sleep = sleep
        self._next_ok = 0.0  # when Reddit will take the next feed request
        self._limit = limit
        self._min_side = min_side
        self._default_tag = default_tag
        self._token = ""
        self._expires = 0.0

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def options(self, manhwa: Manhwa, tag: str | None = None) -> list[ArtOption]:
        # None means "no preference", so the default applies; "" means "just the title".
        extra = self._default_tag if tag is None else tag
        query = " ".join(part for part in (f'"{manhwa.title}"', extra) if part)
        if not (self._id and self._secret):
            return self._from_feed(query)
        params = {"q": query, "type": "link", "sort": "top", "t": "all", "limit": self._limit,
                  "raw_json": 1, "include_over_18": "off"}
        headers = {"Authorization": f"bearer {self._bearer()}", "User-Agent": self._agent}
        try:
            resp = self._client.get(SEARCH_URL, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise MetadataError(f"reddit search failed: {e}") from e
        if resp.status_code >= 400:
            raise MetadataError(f"reddit returned HTTP {resp.status_code} for its search")
        try:
            children = resp.json()["data"]["children"]
        except (ValueError, KeyError, TypeError) as e:
            raise MetadataError(f"could not read the reddit search: {e}") from e

        # Keyed by url: a crosspost lists the same picture again under another subreddit.
        found: dict[str, ArtOption] = {}
        for child in children:
            post = (child or {}).get("data") or {}
            if post.get("over_18"):
                continue
            for option in _pictures(post):
                if min(option.width, option.height) < self._min_side:
                    continue
                found.setdefault(option.url, option)
        # Left in Reddit's order, which is the upvote ranking asked for. Re-arranging is the
        # caller's choice (ArtOrder).
        return list(found.values())

    def fetch(self, option: ArtOption, into: Path) -> Path:
        return download_picture(option.url, into)

    def _from_feed(self, query: str) -> list[ArtOption]:
        """The picture posts of Reddit's public search feed, in its top-voted order."""
        params = {"q": query, "sort": "top", "t": "all", "limit": self._limit,
                  "include_over_18": "off"}
        resp = self._polite_get(FEED_URL, params)
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            raise MetadataError(f"could not read reddit's search feed: {e}") from e
        found: dict[str, tuple[str, str]] = {}
        for entry in root.findall("a:entry", ATOM):
            if not entry.findtext("a:id", "", ATOM).startswith("t3_"):
                continue  # the feed also lists matching subreddits
            match = PICTURE.search(unescape(entry.findtext("a:content", "", ATOM)))
            if not match:
                continue
            category = entry.find("a:category", ATOM)
            sub = category.get("term", "?") if category is not None else "?"
            title = " ".join(entry.findtext("a:title", "", ATOM).split())
            found.setdefault(match.group(1), (sub, title))
        return [
            ArtOption(f"top #{rank}  r/{sub}  {title}"[:80], url)
            for rank, (url, (sub, title)) in enumerate(found.items(), 1)
        ]

    def _polite_get(self, url: str, params: dict) -> httpx.Response:
        """One feed request, kept to Reddit's pace: wait out the window it announced last time,
        and on 429 wait as long as it asks (up to MAX_WAIT) and try once more."""
        for attempt in (1, 2):
            self._wait(self._next_ok - self._clock())
            try:
                resp = self._client.get(
                    url, params=params, headers={"User-Agent": self._agent, **FEED_HEADERS}
                )
            except httpx.HTTPError as e:
                raise MetadataError(f"reddit search failed: {e}") from e
            self._next_ok = self._clock() + max(GAP, _reset(resp) if _spent(resp) else 0.0)
            if resp.status_code != 429:
                break
            asked = _seconds(resp.headers.get("retry-after")) or _reset(resp) or 60.0
            if attempt == 2 or asked > MAX_WAIT:
                raise MetadataError(
                    "reddit says too many requests — wait a few minutes and try again"
                )
            self._next_ok = self._clock() + asked
        if resp.status_code >= 400:
            raise MetadataError(f"reddit returned HTTP {resp.status_code} for its search feed")
        return resp

    def _wait(self, seconds: float) -> None:
        if seconds > 0:
            self._sleep(seconds)

    def _bearer(self) -> str:
        """An app-only token, asked for once and reused until just before it runs out."""
        if not (self._id and self._secret):
            raise ManhwatokError(HINT)
        if self._token and self._clock() < self._expires:
            return self._token
        try:
            resp = self._client.post(
                TOKEN_URL,
                auth=(self._id, self._secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self._agent},
            )
        except httpx.HTTPError as e:
            raise MetadataError(f"could not reach reddit to sign in: {e}") from e
        if resp.status_code in (401, 403):
            raise ManhwatokError(
                f"reddit refused the app credentials (HTTP {resp.status_code}) — check "
                "MANHWATOK_REDDIT_CLIENT_ID and _SECRET, and that the app is approved"
            )
        if resp.status_code >= 400:
            raise MetadataError(f"reddit returned HTTP {resp.status_code} when signing in")
        try:
            body = resp.json()
            self._token = body["access_token"]
            lifetime = float(body.get("expires_in") or 3600)
        except (ValueError, KeyError, TypeError) as e:
            raise MetadataError(f"could not read reddit's sign-in reply: {e}") from e
        self._expires = self._clock() + lifetime - 60
        return self._token


def _pictures(post: dict) -> list[ArtOption]:
    """Every picture in one post: each image of a gallery in its order, or the post's own one."""
    votes = f"⬆ {post.get('score', 0)}"
    where = f"r/{post.get('subreddit', '?')}"
    if post.get("is_gallery"):
        meta = post.get("media_metadata") or {}
        items = (post.get("gallery_data") or {}).get("items") or []
        shown = []
        for item in items:
            media = meta.get(item.get("media_id")) or {}
            ext = MIME_EXT.get(media.get("m", ""))
            if media.get("status") != "valid" or media.get("e") != "Image" or not ext:
                continue
            size = media.get("s") or {}
            shown.append((f"https://i.redd.it/{item['media_id']}.{ext}",
                          _int(size.get("x")), _int(size.get("y"))))
        return [
            ArtOption(f"{votes}  {w}x{h}  {where}  {n}/{len(shown)}", url, w, h)
            for n, (url, w, h) in enumerate(shown, 1)
        ]
    url = post.get("url") or ""
    if post.get("post_hint") != "image" or not url.startswith("https://i.redd.it/"):
        return []
    images = (post.get("preview") or {}).get("images") or [{}]
    source = images[0].get("source") or {}
    w, h = _int(source.get("width")), _int(source.get("height"))
    return [ArtOption(f"{votes}  {w}x{h}  {where}", url, w, h)]


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _spent(resp: httpx.Response) -> bool:
    """Whether Reddit says this window has no requests left."""
    return (_seconds(resp.headers.get("x-ratelimit-remaining")) or 0.0) < 1.0 and (
        "x-ratelimit-remaining" in resp.headers
    )


def _reset(resp: httpx.Response) -> float:
    return _seconds(resp.headers.get("x-ratelimit-reset")) or 0.0


def _seconds(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
