from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn, Optional, TextIO

import typer

from manhwatok.config import Settings
from manhwatok.domain.errors import ManhwatokError
from manhwatok.ports.chapters import PageCount
from manhwatok.domain.models import (
    ArtOrder,
    ArtSourceName,
    ArtStyle,
    ChapterSourceName,
    CoverStyle,
    SearchQuery,
    Sort,
    Visibility,
)

app = typer.Typer(
    help="Themed manhwa recommendation slideshows for TikTok.", no_args_is_help=True
)


@app.callback()
def main() -> None:
    """Themed manhwa recommendation slideshows for TikTok."""


class ProgressLine:
    """Progress messages on stderr. A page count redraws one line as a bar in a terminal;
    anywhere else, and for every other message, each is a line of its own."""

    def __init__(
        self, stream: TextIO | None = None, tty: bool | None = None, width: int = 24
    ) -> None:
        # stderr is looked up on each write unless given, so a test runner that swaps it
        # still sees the messages
        self._given, self._given_tty, self._width = stream, tty, width
        self._open = False

    @property
    def _stream(self) -> TextIO:
        return self._given or sys.stderr

    @property
    def _tty(self) -> bool:
        return self._given_tty if self._given_tty is not None else self._stream.isatty()

    def __call__(self, msg: str) -> None:
        if self._tty and isinstance(msg, PageCount):
            filled = self._width * msg.done // msg.total
            bar = "█" * filled + "░" * (self._width - filled)
            self._open = msg.done < msg.total
            line = f"  {msg.label}  {bar}  {msg.done}/{msg.total}"
            self._write(line, start="\r\x1b[2K", end=not self._open)
            return
        self.close()
        self._write(f"  {msg}", end=True)

    def close(self) -> None:
        """End a bar left unfinished, so what follows starts on its own line."""
        if self._open:
            self._write("", end=True)
            self._open = False

    def _write(self, text: str, start: str = "", end: bool = False) -> None:
        if self._tty and text:
            text = typer.style(text, fg=typer.colors.CYAN)
        self._stream.write(start + text + ("\n" if end else ""))
        self._stream.flush()


_progress = ProgressLine()


def _fail(e: Exception) -> NoReturn:
    _progress.close()
    typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _now() -> datetime:
    """The time the plan's commands work from (tests set their own)."""
    return datetime.now(timezone.utc)


# Search options shared by `suggest` and `build`. Sort and min tag rank default to None so an
# explicit value can override a theme's; plain searches fall back to score / 60.
TAG = typer.Option(
    None, "--tag", "-t", help="AniList tag; repeat to require several (see `manhwatok tags`)."
)
GENRE = typer.Option(None, "--genre", "-g", help="AniList genre; repeat to require several.")
SORT = typer.Option(None, help="Ranking order (default: score, or the theme's).")
LIMIT = typer.Option(12, "--limit", "-n", min=1, max=50, help="How many titles.")
MIN_TAG_RANK = typer.Option(
    None,
    min=0,
    max=100,
    help="Ignore titles where the tag is weaker than this rank (default: 60, or the theme's).",
)
CHAPTERS = typer.Option(
    True, "--chapters/--no-chapters", help="Look up missing chapter counts on MangaUpdates."
)
ACCOUNT = typer.Option(
    None, "--account", "-a", help="Use this account's filters and skip its recent titles."
)
ART = typer.Option(
    None,
    "--art",
    help="Manhwa slide art: 'none' (the cover on its own blur), 'background' (the cover on "
    "AniList's banner art), 'panel' (a wide crop of the banner in place of the cover), "
    "'character' (the title's main character in place of the cover), 'scene' (one picture "
    "filling the whole slide, text over it — for art you picked with `manhwatok art`) or "
    "'quad' (four of the title's own pictures, 2×2: its characters, Pinterest scenes for the "
    "rest, or all scenes with --source). "
    "Default: the account's, else none.",
)


def _query(
    tag: Optional[list[str]],
    genre: Optional[list[str]],
    sort: Optional[Sort],
    limit: int,
    min_tag_rank: Optional[int],
) -> SearchQuery:
    if not tag and not genre:
        raise ManhwatokError("give at least one --tag or --genre")
    return SearchQuery(
        tags=tag or [],
        genres=genre or [],
        sort=sort or Sort.SCORE,
        limit=limit,
        min_tag_rank=60 if min_tag_rank is None else min_tag_rank,
    )


def _theme_query(
    store,
    theme: Optional[str],
    tag: Optional[list[str]],
    genre: Optional[list[str]],
    sort: Optional[Sort],
    limit: int,
    min_tag_rank: Optional[int],
) -> tuple[SearchQuery, str]:
    """(query, default title) from --theme or from -t/-g, never both."""
    from manhwatok.domain.theme import normalize_theme_name

    if theme is None:
        if not tag and not genre:
            raise ManhwatokError("give --theme or at least one --tag or --genre")
        return _query(tag, genre, sort, limit, min_tag_rank), ""
    if tag or genre:
        raise ManhwatokError("use either --theme or -t/-g, not both")
    saved = store.themes.get(normalize_theme_name(theme))
    overrides = {"sort": sort, "min_tag_rank": min_tag_rank}
    query = saved.to_query(limit).model_copy(
        update={k: v for k, v in overrides.items() if v is not None}
    )
    return query, saved.title


def _account(store, handle: Optional[str]):
    from manhwatok.domain.account import normalize_handle

    return store.accounts.get(normalize_handle(handle)) if handle else None


@app.command()
def suggest(
    tag: Optional[list[str]] = TAG,
    genre: Optional[list[str]] = GENRE,
    sort: Optional[Sort] = SORT,
    limit: int = LIMIT,
    min_tag_rank: Optional[int] = MIN_TAG_RANK,
    chapters: bool = CHAPTERS,
    account: Optional[str] = ACCOUNT,
) -> None:
    """Suggest top Korean manhwa matching tags/genres."""
    from manhwatok.app import container
    from manhwatok.app.suggest import suggest_for_account
    from manhwatok.domain.labels import chapter_label

    settings = Settings()
    try:
        query = _query(tag, genre, sort, limit, min_tag_rank)
        with container.build_store(settings) as store:
            results = suggest_for_account(
                query,
                _account(store, account),
                container.build_metadata(settings),
                container.build_chapter_source(settings, store.cache) if chapters else None,
                store.history,
                now=datetime.now(timezone.utc),
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
    account: Optional[str] = ACCOUNT,
    theme: Optional[str] = typer.Option(
        None, "--theme", help="Saved theme to build from (see `manhwatok theme list`)."
    ),
    tag: Optional[list[str]] = TAG,
    genre: Optional[list[str]] = GENRE,
    sort: Optional[Sort] = SORT,
    limit: int = LIMIT,
    min_tag_rank: Optional[int] = MIN_TAG_RANK,
    chapters: bool = CHAPTERS,
    allow_repeats: bool = typer.Option(
        False, "--allow-repeats", help="Also suggest titles the account exported recently."
    ),
    title: Optional[str] = typer.Option(
        None, help="Post title (default: the theme's); wrap words in *stars* to colour them."
    ),
    hashtags: Optional[str] = typer.Option(
        None, help="Caption hashtags (default: the account's, else the standard set)."
    ),
    emojis: Optional[str] = typer.Option(
        None,
        help="Emojis after the title on TikTok; \"auto\" picks them from the post's genres "
        "(default: the account's, else none).",
    ),
    accent: Optional[str] = typer.Option(
        None, help="Accent colour for cover and end slides (default: the account's, else #43c9e4)."
    ),
    art: Optional[ArtStyle] = ART,
) -> None:
    """Build a post: pick titles and hooks in your editor, then render the slides."""
    from manhwatok.app import container
    from manhwatok.app.build_post import build_post
    from manhwatok.app.suggest import suggest_for_account
    from manhwatok.domain.theme import normalize_theme_name

    settings = Settings()
    now = datetime.now(timezone.utc)
    try:
        tools = _tools(settings)
        with container.build_store(settings) as store:
            query, theme_title = _theme_query(store, theme, tag, genre, sort, limit, min_tag_rank)
            acct = _account(store, account)
            metadata = container.build_metadata(settings)
            source = container.build_chapter_source(settings, store.cache) if chapters else None
            built = build_post(
                lambda: suggest_for_account(
                    query, acct, metadata, source, store.history, now, allow_repeats, _progress
                ),
                theme_title if title is None else title,
                acct,
                hashtags,
                accent,
                tools,
                now=now,
                art=art,
                emojis=emojis,
                theme=normalize_theme_name(theme) if theme else None,
            )
    except ManhwatokError as e:
        _fail(e)
    if built is None:
        typer.echo("cancelled — nothing saved")
        return
    post, slides = built
    typer.echo(f"post {post.id} · {len(slides)} slides → {tools.posts.folder(post.id)}")
    typer.echo(f"export with: manhwatok export {post.id}")


@app.command("next")
def next_post(
    account: str = typer.Option(
        ..., "--account", "-a", help="The account whose rotation to follow (see `account set`)."
    ),
    count: int = typer.Option(1, "--count", "-n", min=1, max=20, help="How many posts."),
) -> None:
    """Make an account's next post from its rotation, ready to review.

    A chapter:<title> item builds the title's next part, as `chapter build`; one with nothing
    left is skipped with a warning. A theme:<name> item builds a list post of the theme's first
    picks, as `build --theme` would prefill them, gives its titles art from the account's
    --art-source, as `render --source`, and renders it. Set the rotation with
    `account set <handle> --rotation ...`.
    """
    from manhwatok.app.context import open_context
    from manhwatok.app.next_post import make_next_post

    settings = Settings()
    try:
        ctx = open_context(settings, _progress)
        try:
            for _ in range(count):
                post = make_next_post(ctx, account, datetime.now(timezone.utc), _warn)
                _progress.close()
                typer.echo(f"post {post.id} · {_next_summary(post, ctx.tools.posts)}")
        finally:
            ctx.close()
    except ManhwatokError as e:
        _fail(e)
    typer.echo(
        "review in `manhwatok tui`, or with `manhwatok edit <id>` and "
        "`manhwatok render <id>` (e.g. --source to pick art again)"
    )


def _next_summary(post, posts) -> str:
    """What `next` made: title (or chapter and part), slides, folder."""
    from manhwatok.domain.text import plain_title

    where = post.chapter
    if where is not None:
        what = f"{where.manhwa_title} chapter {where.number} part {where.part}/{where.parts}"
    else:
        what = plain_title(post.title)
    return f"{what} · {post.slide_count} slides → {posts.folder(post.id)}"


@app.command()
def edit(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    art: Optional[ArtStyle] = ART,
) -> None:
    """Reopen a post's draft in your editor and re-render it."""
    from manhwatok.app.edit_post import edit_post
    from manhwatok.app.render_post import restyle

    settings = Settings()
    try:
        tools = _tools(settings)
        if art is not None:
            restyle(post_id, art, tools)
        slides = edit_post(post_id, tools)
    except ManhwatokError as e:
        _fail(e)
    if slides is None:
        typer.echo("no changes")
        return
    typer.echo(f"post {post_id} · {len(slides)} slides → {tools.posts.folder(post_id)}")


@app.command()
def render(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    art: Optional[ArtStyle] = ART,
    source: Optional[ArtSourceName] = typer.Option(
        None,
        "--source",
        help="First give every title a picture from here, as `manhwatok art --pick` would: "
        "'covers' (MangaDex volume covers), 'fanart' (Danbooru), 'pins' (a Pinterest "
        "search, needs gallery-dl) or 'reddit' (most-upvoted image posts; slow, about one "
        "title a minute). Titles you already picked art for keep it.",
    ),
    tag: Optional[str] = typer.Option(
        None,
        "--tag",
        help="Extra words for --source fanart, pins or reddit, e.g. 'fight scene'.",
    ),
    order: Optional[ArtOrder] = typer.Option(
        None,
        "--order",
        help="How --source ranks what it finds: 'relevance' (the source's own order, the "
        "default; 'popular' for --art quad), 'size' (biggest first), 'portrait' (closest to a "
        "slide's 9:16 first) or 'popular' (most liked on Pinterest first).",
    ),
    pick: Optional[int] = typer.Option(
        None, "--pick", metavar="N", min=1, help="Use each title's Nth picture (default: 1)."
    ),
    replace: bool = typer.Option(
        False, "--replace", help="Pick again for titles that already have picked art too."
    ),
    cover: Optional[CoverStyle] = typer.Option(
        None,
        "--cover",
        help="Which cover version becomes 01.png: 'fan' (three covers fanned out), 'quad' "
        "(four characters, one per quadrant) or 'hero' (the first pick's art, full screen). "
        "All three are always written as cover-<version>.png; switch later with "
        "`manhwatok cover`.",
    ),
) -> None:
    """Re-render a post's slides and caption.

    With --source, first gives every title a picture of its own.

    Full-screen Pinterest scenes: --art scene --source pins --order portrait

    With --art quad, --source fills each title's four squares with scenes from there
    (characters stand in where it finds too few). Without it, Pinterest scenes only fill what
    a title's characters leave.
    """
    from manhwatok.app import container
    from manhwatok.app.render_post import render_from_source, render_post, restyle, set_cover

    if source is None:
        given = [
            flag
            for flag, set_ in (
                ("--tag", tag is not None),
                ("--order", order is not None),
                ("--pick", pick is not None),
                ("--replace", replace),
            )
            if set_
        ]
        if given:
            _fail(ManhwatokError(f"{', '.join(given)} only shapes a --source search"))
    elif tag and source is ArtSourceName.COVERS:
        _fail(
            ManhwatokError(
                "--tag narrows --source fanart, pins or reddit; covers has no such vocabulary"
            )
        )

    settings = Settings()
    try:
        tools = _tools(settings)
        if art is not None:
            restyle(post_id, art, tools)
        if cover is not None:
            set_cover(post_id, cover, tools)
        if source is None:
            slides = render_post(post_id, tools)
        else:
            saved = tools.posts.get(post_id)
            with container.build_store(settings) as store:
                sources = container.build_art_sources(settings, store.cache)
                try:
                    filled, slides = render_from_source(
                        post_id, tools, sources[source], tag, order, pick or 1, replace
                    )
                    if filled is not None:
                        typer.echo(
                            f"new {source.value} for {filled} of {len(saved.items)} titles"
                        )
                finally:
                    for built in sources.values():
                        getattr(built, "close", lambda: None)()
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"post {post_id} · {len(slides)} slides → {tools.posts.folder(post_id)}")


@app.command("cover")
def cover_cmd(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    style: Optional[CoverStyle] = typer.Argument(
        None, help="fan, quad or hero. Leave out to list the versions render drew."
    ),
) -> None:
    """Pick which cover version is the post's first slide.

    Every render draws all three next to the slides as cover-fan.png, cover-quad.png and
    cover-hero.png; this swaps the one you like into 01.png without rendering again.
    """
    from manhwatok.app.render_post import choose_cover, cover_version

    settings = Settings()
    try:
        tools = _tools(settings)
        if style is None:
            current = tools.posts.get(post_id).cover
            for one in CoverStyle:
                path = cover_version(post_id, one, tools)
                mark = " (current)" if one is current else ""
                missing = f"not rendered — run: manhwatok render {post_id}"
                where = path if path.is_file() else missing
                typer.echo(f"{one.value}{mark}: {where}")
            typer.echo(f"pick one with: manhwatok cover {post_id} <{'|'.join(CoverStyle)}>")
            return
        first = choose_cover(post_id, style, tools)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"post {post_id} · {style.value} cover → {first}")


@app.command()
def export(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    out: Optional[Path] = typer.Option(
        None, help="Folder to export into (default: ~/Downloads/manhwatok)."
    ),
) -> None:
    """Copy a post's slides and caption.txt to a folder for uploading. Exporting an account's
    post counts its titles as posted."""
    from manhwatok.app import container
    from manhwatok.app.export_post import export_post

    settings = Settings()
    try:
        with container.build_store(settings) as store:
            dest = export_post(
                post_id,
                container.build_posts(settings),
                store.history,
                out or settings.export_dir,
                now=datetime.now(timezone.utc),
                chapters=store.chapters,
            )
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"exported → {dest}")


@app.command()
def posts(
    account: Optional[str] = typer.Option(
        None, "--account", "-a", help="Only this account's posts."
    ),
) -> None:
    """List saved posts, newest first; `for <time>` is when one is scheduled to go out (in
    this computer's time zone), `sent` marks posts confirmed after `upload`."""
    from manhwatok.app import container
    from manhwatok.domain.account import normalize_handle
    from manhwatok.domain.text import plain_title

    try:
        saved = container.build_posts(Settings()).list()
        if account:
            handle = normalize_handle(account)
            saved = [p for p in saved if p.account == handle]
    except ManhwatokError as e:
        _fail(e)
    if not saved:
        hint = "try: manhwatok build -t Revenge"
        typer.echo(f"no posts for @{handle} yet" if account else f"no posts yet — {hint}")
        return
    who = {p.id: f"@{p.account}" if p.account else "-" for p in saved}
    width = max(len(w) for w in who.values())
    any_sent = any(p.sent_at for p in saved)
    any_planned = any(p.scheduled_at for p in saved)
    for post in saved:
        when = post.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
        size = "draft" if post.is_unfinished else f"{post.slide_count} slides"
        planned = ""
        if any_planned:
            at = post.scheduled_at
            planned = f"{f'for {at.astimezone():%Y-%m-%d %H:%M}' if at else '':<20}  "
        sent = f"{'sent' if post.sent_at else '':<4}  " if any_sent else ""
        title = plain_title(post.title) or "(untitled)"
        typer.echo(
            f"{post.id}  {when}  {who[post.id]:<{width}}  {size:>9}  {planned}{sent}{title}"
        )


@app.command()
def art(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    anilist_id: int = typer.Argument(..., help="The title's AniList id, as shown in the draft."),
    picture: Optional[str] = typer.Argument(
        None, help="Image file or URL to use for that title (jpg, png, webp or gif)."
    ),
    clear: bool = typer.Option(
        False, "--clear", help="Drop this title's picked art and go back to its style's own."
    ),
    show: bool = typer.Option(
        False, "--list", help="List the volume covers MangaDex has for this title."
    ),
    pick: Optional[int] = typer.Option(
        None, "--pick", metavar="N", help="Use the Nth picture from --list."
    ),
    source: ArtSourceName = typer.Option(
        ArtSourceName.COVERS,
        "--source",
        help="Where --list looks: 'covers' (MangaDex volume covers), 'fanart' (Danbooru, "
        "best-scored and safe-rated only), 'pins' (a Pinterest search, needs gallery-dl) or "
        "'reddit' (most-upvoted image posts; slow, Reddit allows about one search a minute).",
    ),
    tag: Optional[str] = typer.Option(
        None,
        "--tag",
        help="Extra words for --source fanart, pins or reddit, e.g. 'full_body'. On fanart it "
        "costs the score ordering, so results are ranked afterwards instead.",
    ),
    order: ArtOrder = typer.Option(
        ArtOrder.RELEVANCE,
        "--order",
        help="How to arrange --list: 'relevance' (the source's own order), 'size' (biggest "
        "first), 'portrait' (closest to a slide's 9:16 first) or 'popular' (most liked on "
        "Pinterest first).",
    ),
) -> None:
    """Use a picture of your own for one title, instead of the art its style would fetch.

    With --list, offers what another catalogue has for the title instead: MangaDex's volume
    covers by default, or fan art from Danbooru with --source fanart.
    """
    import shlex
    import tempfile

    from manhwatok.adapters.picture_download import download_picture, looks_like_url
    from manhwatok.app import container
    from manhwatok.app.art_options import list_art, use_art
    from manhwatok.app.item_art import clear_item_art, set_item_art
    from manhwatok.app.render_post import render_post

    asked = [
        name
        for name, given in (
            ("a picture", picture is not None),
            ("--clear", clear),
            ("--list", show),
            ("--pick", pick is not None),
        )
        if given
    ]
    if len(asked) != 1:
        got = f" (got {', '.join(asked)})" if asked else ""
        _fail(ManhwatokError(f"give exactly one of: a picture, --clear, --list or --pick N{got}"))
    if tag and source is ArtSourceName.COVERS:
        _fail(
            ManhwatokError(
                "--tag narrows --source fanart, pins or reddit; covers has no such vocabulary"
            )
        )

    settings = Settings()
    try:
        tools = _tools(settings)
        if show or pick is not None:
            with container.build_store(settings) as store:
                sources = container.build_art_sources(settings, store.cache)
                art_source = sources[source]
                # --pick re-runs the search, so the hint has to carry everything that shaped
                # the list; dropping one points the user at a different list than they just saw.
                shaped = "".join(
                    (
                        "" if source is ArtSourceName.COVERS else f" --source {source.value}",
                        f" --tag {shlex.quote(tag)}" if tag else "",
                        "" if order is ArtOrder.RELEVANCE else f" --order {order.value}",
                    )
                )
                try:
                    options = list_art(post_id, anilist_id, tools, art_source, tag, order)
                    if show:
                        if not options:
                            typer.echo(f"no {source.value} found for {anilist_id}")
                            return
                        for number, option in enumerate(options, 1):
                            typer.echo(f"  {number}  {option.label}")
                        typer.echo(
                            f"use one with: manhwatok art {post_id} {anilist_id}"
                            f"{shaped} --pick N"
                        )
                        return
                    if not 1 <= pick <= len(options):
                        many = f"1-{len(options)}" if options else "none at all"
                        raise ManhwatokError(f"no cover {pick} for {anilist_id} — it has {many}")
                    chosen = options[pick - 1]
                    typer.echo(f"downloading {chosen.label}")
                    kept = use_art(post_id, anilist_id, chosen, tools, art_source)
                    typer.echo(f"using {kept.name} ({chosen.label}) for {anilist_id}")
                finally:
                    for built in sources.values():
                        getattr(built, "close", lambda: None)()
        elif clear:
            clear_item_art(post_id, anilist_id, tools)
            typer.echo(f"dropped the picked art for {anilist_id}")
        elif looks_like_url(picture):
            # Kept only until it is copied into the post's folder.
            with tempfile.TemporaryDirectory() as scratch:
                typer.echo(f"downloading {picture}")
                got = download_picture(picture, Path(scratch))
                kept = set_item_art(post_id, anilist_id, got, tools)
            typer.echo(f"using {kept.name} for {anilist_id}")
        else:
            kept = set_item_art(post_id, anilist_id, Path(picture).expanduser(), tools)
            typer.echo(f"using {kept.name} for {anilist_id}")
        slides = render_post(post_id, tools)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"post {post_id} · {len(slides)} slides → {tools.posts.folder(post_id)}")


@app.command()
def delete(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for confirmation."),
) -> None:
    """Delete a post's folder. An exported post's titles still count as posted."""
    from manhwatok.app import container
    from manhwatok.app.delete_post import delete_post, leftover_state
    from manhwatok.domain.errors import PostNotFound

    settings = Settings()
    try:
        repo = container.build_posts(settings)
        try:
            post = repo.get(post_id)
            size = "draft" if post.is_unfinished else f"{post.slide_count} slides"
        except PostNotFound:
            size = leftover_state(post_id, repo)  # an empty or broken folder can still go
        if not yes and not typer.confirm(f"Delete post {post_id} ({size})?", default=False):
            typer.echo("kept")
            return
        with container.build_store(settings) as store:
            delete_post(post_id, repo, chapters=store.chapters)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"deleted post {post_id}")


@app.command()
def tui() -> None:
    """Open the terminal app: posts with slide previews, building, accounts and themes."""
    try:
        from manhwatok.tui.app import run
    except ImportError as e:
        if (e.name or "").split(".")[0] not in ("textual", "textual_image"):
            raise
        _fail(ManhwatokError("the TUI needs the tui extra — run: uv sync --extra tui"))
    try:
        run(Settings())
    except ManhwatokError as e:
        _fail(e)


# --- assisted upload -----------------------------------------------------------------------


def _ask(question: str) -> bool:
    """A yes/no question that defaults to no; no answer at all (Ctrl-D, Ctrl-C) is a no too."""
    try:
        return typer.confirm(question, default=False)
    except typer.Abort:
        typer.echo()
        return False


def _choose_sound(sounds: list[str]) -> Optional[str]:
    """Numbered list of the account's sounds; Enter takes the first, 0 means none. No answer
    at all (Ctrl-D, Ctrl-C) is no sound."""
    typer.echo("Sound for this post:")
    for n, sound in enumerate(sounds, 1):
        typer.echo(f"  {n}. {sound}")
    typer.echo("  0. no sound")
    while True:
        try:
            answer = typer.prompt("Pick", default=1, type=int)
        except typer.Abort:
            typer.echo()
            return None
        if answer == 0:
            return None
        if 1 <= answer <= len(sounds):
            return sounds[answer - 1]
        typer.echo(f"pick 0–{len(sounds)}")


def _ctrl_c(message: str) -> NoReturn:
    """Ctrl-C while the browser was open; it's closed by now. Exit like an interrupted
    command (130), without a traceback."""
    typer.echo()
    typer.echo(message)
    raise typer.Exit(code=130)


@app.command()
def login(handle: str = typer.Argument(..., help="TikTok handle, e.g. @manhwa.daily")) -> None:
    """Log in to TikTok as an account, once, in that account's own browser window."""
    from manhwatok.app import container
    from manhwatok.app.login_account import login_account

    settings = Settings()
    try:
        with container.build_store(settings) as store:
            account = login_account(
                handle, store.accounts, container.build_uploader(settings), typer.echo
            )
    except ManhwatokError as e:
        _fail(e)
    except KeyboardInterrupt:
        _ctrl_c("stopped — browser closed")
    typer.echo(f"browser closed — once logged in, `manhwatok upload` posts as {account.display}")


SLOT = "slot"  # `--at slot`: the post's own place in the plan


def _upload_schedule(
    post, account, at: Optional[str], no_schedule: bool, now
) -> Optional[datetime]:
    """When TikTok should post it: `--at`, or — by default — the post's own planned time,
    when TikTok would still take it. None means an ordinary upload, to go out now."""
    from manhwatok.app.upload_post import schedule_for
    from manhwatok.domain.plan import check_schedule, parse_when

    if no_schedule:
        if at is not None:
            raise ManhwatokError("give --at or --no-schedule, not both")
        return None
    if at is None:
        return schedule_for(post, now)
    if at.strip().lower() == SLOT:
        if post.scheduled_at is None:
            raise ManhwatokError(
                f'post {post.id} has no time of its own — give --at "YYYY-MM-DD HH:MM", or '
                f"set one with: manhwatok schedule {post.id} <when>"
            )
        return check_schedule(post.scheduled_at, now)
    return check_schedule(parse_when(at, account.timezone, now), now)


def _upload_line(
    post_id: str,
    account,
    when: Optional[datetime],
    visibility=Visibility.EVERYONE,
    chose=None,
) -> str:
    """What the upload is about to do, said before the browser opens. Who can see it is only
    worth saying when it isn't everyone — TikTok's own default — and the sound only when
    chance chose it, since nothing else asked for that one."""
    from zoneinfo import ZoneInfo

    seen = "" if visibility is Visibility.EVERYONE else f", visible to {visibility.spoken}"
    luck = f', sound: "{chose.sound}" (picked at random)' if chose and chose.at_random else ""
    if when is None:
        return f"post {post_id} → {account.display}{seen}, posting now{luck}"
    local = when.astimezone(ZoneInfo(account.timezone))
    return (
        f"post {post_id} → {account.display}{seen}, scheduled for {local:%a %d %b %H:%M} "
        f"({account.timezone}){luck}"
    )


@app.command()
def upload(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    debug: bool = typer.Option(
        False, "--debug", help="Save a screenshot and the page's HTML if something isn't found."
    ),
    sound: Optional[str] = typer.Option(
        None,
        "--sound",
        help="Search TikTok's sounds for this and use the first one found (default: the "
        "account's --default-sound, or the post's theme's sound when it has one, else ask).",
    ),
    no_sound: bool = typer.Option(False, "--no-sound", help="Add no sound, don't ask."),
    ask_sound: bool = typer.Option(
        False, "--ask-sound", help="Ask which sound to use, even with a default one set."
    ),
    random_sound: bool = typer.Option(
        False,
        "--random-sound",
        help="Pick one of the sounds on offer at random instead of asking (as the account's "
        "--random-sound). With no sound to pick from, it asks as usual; --ask-sound and "
        "--sound/--no-sound beat it.",
    ),
    at: Optional[str] = typer.Option(
        None,
        "--at",
        metavar="WHEN",
        help="Fill TikTok's own schedule in with this time instead of posting now: "
        '"YYYY-MM-DD HH:MM" or "<day> HH:MM" (the next such time) in the account\'s time '
        'zone, or "slot" for the post\'s own planned time. TikTok takes 15 minutes to 10 '
        "days ahead, on 5 minutes.",
    ),
    no_schedule: bool = typer.Option(
        False, "--no-schedule", help="Post it now, even if the post is planned for later."
    ),
    visibility: Optional[Visibility] = typer.Option(
        None,
        "--visibility",
        help="Who can see this one upload: everyone, friends (followers you follow back) or "
        "private (only you). Beats the post's own choice (`manhwatok visibility`) and the "
        "account's --visibility; nothing is saved. TikTok's own default is everyone.",
    ),
) -> None:
    """Open TikTok's upload page as the post's account with the slides, title, description and
    sound filled in. A post planned for later (`plan fill`, `schedule`) also gets TikTok's own
    schedule filled in. You check it and click Post — or Schedule — yourself, then answer y
    here to record the post as sent."""
    from manhwatok.app import container
    from manhwatok.app.upload_post import sound_choice, upload_post, visibility_for

    settings = Settings()
    now = datetime.now(timezone.utc)
    try:
        if no_sound and sound is not None:
            raise ManhwatokError("give --sound or --no-sound, not both")
        with container.build_store(settings) as store:
            posts = container.build_posts(settings)
            when = None
            asked = "" if no_sound else sound
            post = posts.get(post_id)
            if post.account:  # without one, upload_post says what to do about it
                account = store.accounts.get(post.account)
                when = _upload_schedule(post, account, at, no_schedule, now)
                seen = visibility_for(post, account, visibility)
                # Chosen here, once, so the line says the very sound the browser will get:
                # asking `upload_post` to pick again would be a second roll of the dice.
                chose = sound_choice(
                    post, account, store.themes, asked, ask_sound, random_sound=random_sound
                )
                asked = None if chose.ask else chose.sound or ""
                typer.echo(_upload_line(post_id, account, when, seen, chose))
            posted = upload_post(
                post_id,
                posts,
                store.accounts,
                store.history,
                container.build_uploader(settings),
                _ask,
                typer.echo,
                now=now,
                debug=debug,
                sound=asked,
                choose_sound=_choose_sound,
                themes=store.themes,
                chapters=store.chapters,
                schedule_at=when,
                ask_sound=ask_sound,
                visibility=visibility,
            )
    except ManhwatokError as e:
        _fail(e)
    except KeyboardInterrupt:
        _ctrl_c("nothing recorded")
    typer.echo(f"recorded post {post_id} as sent" if posted else "nothing recorded")


# --- accounts and themes -------------------------------------------------------------------

account_app = typer.Typer(
    help="TikTok accounts: genre filters, hashtags, accent, end-slide texts.",
    no_args_is_help=True,
)
theme_app = typer.Typer(
    help="Themes: reusable tags/genres + title, shared by every account.", no_args_is_help=True
)
chapter_app = typer.Typer(
    help="Publish a manhwa's chapters, a part at a time. The pages come from MangaDex, which "
    "hosts fan translations: whether you have the rights to repost a chapter is your call, and "
    "copyright holders do have TikTok accounts taken down.",
    no_args_is_help=True,
)
app.add_typer(account_app, name="account")
app.add_typer(theme_app, name="theme")
app.add_typer(chapter_app, name="chapter")


def _warn(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.YELLOW, err=True)


# Account options shared by `account add` and `account set`; None means "not given".
GENRES = typer.Option(
    None, "--genres", help='Allowed genres, comma-separated; a title needs one. "" clears.'
)
BLOCK_GENRES = typer.Option(
    None, "--block-genres", help="Genres never to suggest, comma-separated."
)
BLOCK_TAGS = typer.Option(None, "--block-tags", help="Tags never to suggest, comma-separated.")
ACCOUNT_HASHTAGS = typer.Option(None, "--hashtags", help="Caption hashtags for this account.")
ACCOUNT_EMOJIS = typer.Option(
    None,
    "--emojis",
    help='Emojis after the title on TikTok, e.g. "🔥📚"; "auto" picks them from each post\'s '
    'genres. "" clears.',
)
ACCOUNT_SOUNDS = typer.Option(
    None,
    "--sound",
    help="A TikTok sound search, e.g. \"SOLO LEVELING RaijinLofi\"; repeat for several. "
    "Replaces the account's list; --sound \"\" clears it. `upload` asks which one to use.",
)
DEFAULT_SOUND = typer.Option(
    None,
    "--default-sound",
    help="The sound `upload` uses for this account without asking, e.g. \"SOLO LEVELING "
    'RaijinLofi". "" clears it and brings the question back; `upload --ask-sound` asks once.',
)
RANDOM_SOUND = typer.Option(
    None,
    "--random-sound/--no-random-sound",
    help="Let chance pick one of this account's sounds (its --default-sound and --sound, or a "
    "post's theme's own) for every upload, instead of asking. `upload --ask-sound` still "
    "asks, and `upload --sound`/`--no-sound` still decide for one post.",
)
ACCOUNT_ACCENT = typer.Option(None, "--accent", help="Accent colour, e.g. #43c9e4.")
CTA_TITLE = typer.Option(None, "--cta-title", help="End-slide title; *word* = accent colour.")
CTA_FOLLOW = typer.Option(None, "--cta-follow", help="End-slide follow line.")
ACCOUNT_ART = typer.Option(
    None, "--art", help="Default manhwa slide art for this account's new posts."
)
REPEAT_DAYS = typer.Option(
    None, "--repeat-days", min=1, max=3650, help="Don't suggest titles exported this recently."
)
ROTATION = typer.Option(
    None,
    "--rotation",
    help="What `manhwatok next` posts, in turn, comma-separated: chapter:<title> (its next "
    "part, as `chapter build`) or theme:<name> (a list post of the theme's first picks), e.g. "
    '"chapter:Solo Leveling,theme:isekai". Repeat an item to post it more often. Setting it '
    'starts the rotation over; "" clears it.',
)
TIMEZONE = typer.Option(
    None, "--timezone", help="The account's time zone, e.g. Europe/Paris (the default)."
)
SLOTS = typer.Option(
    None,
    "--slots",
    help="When this account's posts go out each week, in its --timezone, comma-separated: "
    '<day> HH:MM with day mon..sun or daily, e.g. "mon 19:00,thu 19:00". `manhwatok plan '
    'fill` makes a post for each. "" clears them.',
)
ACCOUNT_VISIBILITY = typer.Option(
    None,
    "--visibility",
    help="Who can see this account's posts: everyone (the default, and TikTok's own), friends "
    "(followers you follow back) or private (only you). One post can say otherwise with "
    "`manhwatok visibility`, and `upload --visibility` beats both.",
)
ART_SOURCE = typer.Option(
    None,
    "--art-source",
    help="Where `manhwatok next` fills a list post's art from, as `render --source`: covers, "
    'fanart, pins or reddit. "" (the default) keeps each style\'s own art.',
)


def _account_fields(
    genres: Optional[str],
    block_genres: Optional[str],
    block_tags: Optional[str],
    hashtags: Optional[str],
    accent: Optional[str],
    cta_title: Optional[str],
    cta_follow: Optional[str],
    repeat_days: Optional[int],
    art: Optional[ArtStyle],
    emojis: Optional[str] = None,
    sounds: Optional[list[str]] = None,
    default_sound: Optional[str] = None,
    random_sound: Optional[bool] = None,
    rotation: Optional[str] = None,
    time_zone: Optional[str] = None,
    art_source: Optional[str] = None,
    slots: Optional[str] = None,
    visibility: Optional[Visibility] = None,
) -> dict:
    from manhwatok.domain.text import split_names

    lists = {"genres": genres, "block_genres": block_genres, "block_tags": block_tags}
    fields: dict = {k: split_names(v) for k, v in lists.items() if v is not None}
    scalars = {
        "hashtags": hashtags,
        "emojis": emojis,
        "default_sound": default_sound,
        "random_sound": random_sound,
        "accent": accent,
        "cta_title": cta_title,
        "cta_follow": cta_follow,
        "repeat_days": repeat_days,
        "art": art,
        "visibility": visibility,
    }
    fields.update({k: v for k, v in scalars.items() if v is not None})
    if sounds:  # typer gives [] when --sound wasn't used
        fields["sounds"] = sounds
    if rotation is not None:
        # Not split_names: a rotation keeps its repeats. A new rotation starts from the top,
        # since the old place in it means nothing in the new one.
        fields["rotation"] = [item.strip() for item in rotation.split(",") if item.strip()]
        fields["rotation_cursor"] = 0
    if time_zone is not None:
        fields["timezone"] = time_zone
    if art_source is not None:
        fields["art_source"] = art_source.strip() or None
    if slots is not None:
        fields["slots"] = [slot.strip() for slot in slots.split(",") if slot.strip()]
    return fields


def _print_account(a) -> None:
    typer.secho(a.display, bold=True)
    for label, value in [
        ("genres", ", ".join(a.genres) or "any"),
        ("block genres", ", ".join(a.block_genres) or "-"),
        ("block tags", ", ".join(a.block_tags) or "-"),
        ("hashtags", a.hashtags or "-"),
        ("emojis", a.emojis or "-"),
        ("sounds", " | ".join(a.sounds) or "-"),
        ("default sound", a.default_sound or "-"),
        ("random sound", "yes" if a.random_sound else "no"),
        ("accent", a.accent),
        ("cta title", a.cta_title),
        ("cta follow", a.cta_follow),
        ("repeat days", str(a.repeat_days)),
        ("art", a.art.value),
        ("rotation", _rotation_text(a)),
        ("timezone", a.timezone),
        ("slots", ", ".join(a.slots) or "-"),
        ("art source", a.art_source.value if a.art_source else "-"),
        ("visibility", a.visibility.value),
    ]:
        typer.echo(f"  {label:<13} {value}")


def _rotation_text(a) -> str:
    """The rotation, and the item `next` makes a post of next."""
    from manhwatok.domain.plan import next_item

    if not a.rotation:
        return "-"
    upcoming, _ = next_item(a.rotation, a.rotation_cursor)
    return f"{', '.join(a.rotation)} (next: {upcoming})"


def _save_account(action, verb: str, handle: str, fields: dict) -> None:
    from manhwatok.app import container
    from manhwatok.app.names import AniListNames

    settings = Settings()
    try:
        with container.build_store(settings) as store:
            names = AniListNames(container.build_metadata(settings), store.cache, _warn)
            account = action(store.accounts, names, handle, fields)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"{verb} {account.display}")
    _print_account(account)


@account_app.command("add")
def account_add(
    handle: str = typer.Argument(..., help="TikTok handle, e.g. @manhwa.daily"),
    genres: Optional[str] = GENRES,
    block_genres: Optional[str] = BLOCK_GENRES,
    block_tags: Optional[str] = BLOCK_TAGS,
    hashtags: Optional[str] = ACCOUNT_HASHTAGS,
    emojis: Optional[str] = ACCOUNT_EMOJIS,
    sound: Optional[list[str]] = ACCOUNT_SOUNDS,
    default_sound: Optional[str] = DEFAULT_SOUND,
    random_sound: Optional[bool] = RANDOM_SOUND,
    accent: Optional[str] = ACCOUNT_ACCENT,
    cta_title: Optional[str] = CTA_TITLE,
    cta_follow: Optional[str] = CTA_FOLLOW,
    repeat_days: Optional[int] = REPEAT_DAYS,
    art: Optional[ArtStyle] = ACCOUNT_ART,
    rotation: Optional[str] = ROTATION,
    time_zone: Optional[str] = TIMEZONE,
    art_source: Optional[str] = ART_SOURCE,
    slots: Optional[str] = SLOTS,
    visibility: Optional[Visibility] = ACCOUNT_VISIBILITY,
) -> None:
    """Add an account; unset options get the defaults."""
    from manhwatok.app.accounts import add_account

    fields = _account_fields(
        genres, block_genres, block_tags, hashtags, accent, cta_title, cta_follow, repeat_days, art,
        emojis, sound, default_sound, random_sound, rotation, time_zone, art_source,
        slots, visibility,
    )
    _save_account(add_account, "added", handle, fields)


@account_app.command("set")
def account_set(
    handle: str = typer.Argument(..., help="TikTok handle, e.g. @manhwa.daily"),
    genres: Optional[str] = GENRES,
    block_genres: Optional[str] = BLOCK_GENRES,
    block_tags: Optional[str] = BLOCK_TAGS,
    hashtags: Optional[str] = ACCOUNT_HASHTAGS,
    emojis: Optional[str] = ACCOUNT_EMOJIS,
    sound: Optional[list[str]] = ACCOUNT_SOUNDS,
    default_sound: Optional[str] = DEFAULT_SOUND,
    random_sound: Optional[bool] = RANDOM_SOUND,
    accent: Optional[str] = ACCOUNT_ACCENT,
    cta_title: Optional[str] = CTA_TITLE,
    cta_follow: Optional[str] = CTA_FOLLOW,
    repeat_days: Optional[int] = REPEAT_DAYS,
    art: Optional[ArtStyle] = ACCOUNT_ART,
    rotation: Optional[str] = ROTATION,
    time_zone: Optional[str] = TIMEZONE,
    art_source: Optional[str] = ART_SOURCE,
    slots: Optional[str] = SLOTS,
    visibility: Optional[Visibility] = ACCOUNT_VISIBILITY,
) -> None:
    """Change an account; only the given options change."""
    from manhwatok.app.accounts import update_account

    fields = _account_fields(
        genres, block_genres, block_tags, hashtags, accent, cta_title, cta_follow, repeat_days, art,
        emojis, sound, default_sound, random_sound, rotation, time_zone, art_source,
        slots, visibility,
    )
    _save_account(update_account, "updated", handle, fields)


@account_app.command("list")
def account_list() -> None:
    """One line per account."""
    from manhwatok.app import container

    try:
        with container.build_store(Settings()) as store:
            accounts = store.accounts.list()
    except ManhwatokError as e:
        _fail(e)
    if not accounts:
        typer.echo("no accounts yet — try: manhwatok account add @yourhandle")
        return
    width = max(len(a.display) for a in accounts)
    for a in accounts:
        blocks = a.block_genres + a.block_tags
        typer.echo(
            f"{a.display:<{width}}  {', '.join(a.genres) or 'any genre'}  "
            f"{'blocks ' + ', '.join(blocks) if blocks else 'no blocks'}  repeat {a.repeat_days}d"
        )


@account_app.command("show")
def account_show(handle: str = typer.Argument(..., help="TikTok handle.")) -> None:
    """Every setting of one account."""
    from manhwatok.app import container
    from manhwatok.domain.account import normalize_handle

    try:
        with container.build_store(Settings()) as store:
            account = store.accounts.get(normalize_handle(handle))
    except ManhwatokError as e:
        _fail(e)
    _print_account(account)


@account_app.command("remove")
def account_remove(
    handle: str = typer.Argument(..., help="TikTok handle."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Also delete its saved TikTok login without asking."
    ),
) -> None:
    """Remove an account. Its posting history is kept, so re-adding it keeps repeat protection."""
    from manhwatok.app import container
    from manhwatok.app.login_account import forget_login, saved_login
    from manhwatok.domain.account import normalize_handle

    settings = Settings()
    try:
        with container.build_store(settings) as store:
            h = normalize_handle(handle)
            store.accounts.remove(h)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"removed @{h} (its posting history is kept)")
    try:
        profile = saved_login(settings.browser_dir, h)
        if profile is None:
            return
        if not yes and not _ask(f"Also delete the saved TikTok login for @{h}?"):
            typer.echo(f"kept the saved TikTok login in {profile}")
            return
        forget_login(settings.browser_dir, h)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"deleted the saved TikTok login for @{h}")


def _print_theme(t) -> None:
    typer.secho(t.name, bold=True)
    for label, value in [
        ("title", t.title),
        ("tags", ", ".join(t.tags) or "-"),
        ("genres", ", ".join(t.genres) or "-"),
        ("sort", t.sort.value),
        ("min tag rank", str(t.min_tag_rank)),
        ("sounds", " | ".join(t.sounds) or "-"),
    ]:
        typer.echo(f"  {label:<13} {value}")


THEME_SOUND = typer.Option(
    None,
    "--sound",
    help="A TikTok sound search that suits this kind of post, e.g. 'Close Eyes DVRST'. Repeat "
    "for several. `upload` offers a post's theme sounds before its account's.",
)


@theme_app.command("add")
def theme_add(
    name: str = typer.Argument(..., help="Theme name, e.g. regression-revenge."),
    tag: Optional[list[str]] = TAG,
    genre: Optional[list[str]] = GENRE,
    title: str = typer.Option(..., "--title", help="Post title; wrap words in *stars* to colour."),
    sort: Sort = typer.Option(Sort.SCORE, help="Ranking order."),
    min_tag_rank: int = typer.Option(
        60, min=0, max=100, help="Ignore titles where the tag is weaker than this rank."
    ),
    sound: Optional[list[str]] = THEME_SOUND,
) -> None:
    """Save a theme: the search filters and title for one kind of post."""
    from manhwatok.app import container
    from manhwatok.app.accounts import add_theme
    from manhwatok.app.names import AniListNames

    settings = Settings()
    try:
        with container.build_store(settings) as store:
            names = AniListNames(container.build_metadata(settings), store.cache, _warn)
            theme = add_theme(
                store.themes,
                names,
                name,
                tag or [],
                genre or [],
                sort,
                min_tag_rank,
                title,
                sound or [],
            )
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"added theme {theme.name}")
    _print_theme(theme)


@theme_app.command("set")
def theme_set(
    name: str = typer.Argument(..., help="Theme name."),
    tag: Optional[list[str]] = TAG,
    genre: Optional[list[str]] = GENRE,
    title: Optional[str] = typer.Option(None, "--title", help="Post title."),
    sort: Optional[Sort] = typer.Option(None, help="Ranking order."),
    min_tag_rank: Optional[int] = typer.Option(
        None, min=0, max=100, help="Ignore titles where the tag is weaker than this rank."
    ),
    sound: Optional[list[str]] = THEME_SOUND,
) -> None:
    """Change a theme; only the given options change. Repeated --sound replaces its sounds."""
    from manhwatok.app import container
    from manhwatok.app.accounts import update_theme
    from manhwatok.app.names import AniListNames

    changes: dict = {}
    if tag:
        changes["tags"] = tag
    if genre:
        changes["genres"] = genre
    if title is not None:
        changes["title"] = title
    if sort is not None:
        changes["sort"] = sort
    if min_tag_rank is not None:
        changes["min_tag_rank"] = min_tag_rank
    if sound:  # typer gives [] when --sound wasn't used
        changes["sounds"] = sound
    if not changes:
        _fail(ManhwatokError("nothing to change — give at least one option"))
    settings = Settings()
    try:
        with container.build_store(settings) as store:
            names = AniListNames(container.build_metadata(settings), store.cache, _warn)
            theme = update_theme(store.themes, names, name, changes)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"updated theme {theme.name}")
    _print_theme(theme)


@theme_app.command("list")
def theme_list() -> None:
    """One line per theme."""
    from manhwatok.app import container
    from manhwatok.domain.text import plain_title

    try:
        with container.build_store(Settings()) as store:
            themes = store.themes.list()
    except ManhwatokError as e:
        _fail(e)
    if not themes:
        typer.echo('no themes yet — try: manhwatok theme add revenge -t Revenge --title "..."')
        return
    for t in themes:
        filters = ", ".join(t.tags + t.genres)
        typer.echo(f"{t.name}  {plain_title(t.title)}  [{filters}]  {t.sort.value}")


@theme_app.command("show")
def theme_show(name: str = typer.Argument(..., help="Theme name.")) -> None:
    """Every setting of one theme."""
    from manhwatok.app import container
    from manhwatok.domain.theme import normalize_theme_name

    try:
        with container.build_store(Settings()) as store:
            theme = store.themes.get(normalize_theme_name(name))
    except ManhwatokError as e:
        _fail(e)
    _print_theme(theme)


@theme_app.command("remove")
def theme_remove(name: str = typer.Argument(..., help="Theme name.")) -> None:
    """Remove a theme (posts built from it are unaffected)."""
    from manhwatok.app import container
    from manhwatok.domain.theme import normalize_theme_name

    try:
        with container.build_store(Settings()) as store:
            n = normalize_theme_name(name)
            store.themes.remove(n)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"removed theme {n}")


# --- chapters ---------------------------------------------------------------------------------

TITLE_ARG = typer.Argument(..., help="Manhwa title, or its AniList id.", metavar="TITLE")


def _close(source) -> None:
    getattr(source, "close", lambda: None)()


LANGUAGE = typer.Option("en", "--language", help="Chapter language to publish.")
SOURCE = typer.Option(
    None,
    "--source",
    help="Where the pages come from: 'mangadex' (fan translations, wider catalogue), "
    "'webtoons' (the publisher's own English from episode 1, free episodes only) or 'asura' "
    "(Asura's own translations of ongoing action manhwa, whole runs). Default: "
    "whichever the title is already tracked under, else the first that has it. A title keeps "
    "its source, because chapter numbers don't mean the same thing in two catalogues.",
)


def _chapter_parts(settings, store, text: str, language: str, source=None):
    """(title, chapter tools, its chapters) for a named title — the three every command here
    starts from. Lists from the source the first time a title is asked about."""
    from manhwatok.app import container
    from manhwatok.app.chapter_post import pick_source, refresh_chapters, resolve_title

    manhwa = resolve_title(text, container.build_metadata(settings), store.cache)
    tools = pick_source(
        manhwa, container.build_chapter_tools(settings, store), language, source, _progress
    )
    known = store.chapters.chapters(manhwa.anilist_id, language, tools.source)
    if not known:
        known = refresh_chapters(manhwa, tools, datetime.now(timezone.utc), language, _progress)
    return manhwa, tools, known


@chapter_app.command("list")
def chapter_list(
    title: str = TITLE_ARG,
    refresh: bool = typer.Option(False, "--refresh", help="Ask the source for new chapters."),
    language: str = LANGUAGE,
    source: Optional[ChapterSourceName] = SOURCE,
) -> None:
    """A title's chapters: their pages, what was built from them and what went out."""
    from manhwatok.app import container
    from manhwatok.app.chapter_post import chapter_status, missing_report, refresh_chapters

    settings = Settings()
    try:
        with container.build_store(settings) as store:
            manhwa, tools, _ = _chapter_parts(settings, store, title, language, source)
            if refresh:
                refresh_chapters(manhwa, tools, datetime.now(timezone.utc), language, _progress)
            rows = chapter_status(manhwa.anilist_id, tools, language)
            gaps = missing_report(manhwa, tools, [r.chapter for r in rows], language)
            for reader in tools.sources.values():
                _close(reader)
    except ManhwatokError as e:
        _fail(e)
    typer.secho(f"{manhwa.title} ({manhwa.anilist_id}) · {tools.source.value}", bold=True)
    for row in rows:
        built = f"{row.built}/{row.parts[0].parts} parts" if row.built else "-"
        published = f"published {row.parts[0].published_at:%Y-%m-%d}" if row.published else ""
        downloaded = "downloaded" if row.chapter.downloaded_at else ""
        cells = [f"ch. {row.chapter.number:<8}", f"{row.chapter.pages:>3} pages"]
        typer.echo("  " + "  ".join(cells + [f"{downloaded:<10}", f"{built:<10}", published]).rstrip())
    for line in gaps:
        _warn(line)
    typer.echo(f"build the next part with: manhwatok chapter build {manhwa.anilist_id}")


@chapter_app.command("next")
def chapter_next(
    title: str = TITLE_ARG,
    language: str = LANGUAGE,
    source: Optional[ChapterSourceName] = SOURCE,
) -> None:
    """Which chapter and part `chapter build` would make next."""
    from manhwatok.app import container
    from manhwatok.domain.chapter import next_part

    settings = Settings()
    try:
        with container.build_store(settings) as store:
            manhwa, tools, known = _chapter_parts(settings, store, title, language, source)
            found = next_part(
                known, store.chapters.parts(manhwa.anilist_id, language, tools.source)
            )
            for reader in tools.sources.values():
                _close(reader)
    except ManhwatokError as e:
        _fail(e)
    if found is None:
        typer.echo(f"every listed chapter of {manhwa.title} is already built")
        return
    parts = f" of {found.parts}" if found.parts else ""
    typer.echo(f"next: chapter {found.chapter.number}, part {found.part}{parts}")
    typer.echo(f"build it with: manhwatok chapter build {manhwa.anilist_id}")


@chapter_app.command("build")
def chapter_build(
    title: str = TITLE_ARG,
    number: Optional[str] = typer.Option(
        None, "--number", help="Chapter to publish (default: the next one not built)."
    ),
    part: Optional[int] = typer.Option(
        None, "--part", min=1, help="Which part of it (default: the next one not built)."
    ),
    account: Optional[str] = ACCOUNT,
    language: str = LANGUAGE,
    source: Optional[ChapterSourceName] = SOURCE,
    title_text: Optional[str] = typer.Option(
        None, "--title", help="Post title; wrap words in *stars* to colour."
    ),
    hashtags: Optional[str] = typer.Option(None, help="Caption hashtags."),
    accent: Optional[str] = typer.Option(None, help="Accent colour for the cover and end slide."),
    emojis: Optional[str] = typer.Option(None, help="Emojis after the title on TikTok."),
) -> None:
    """Build one post from a chapter: its pages, cut into slides."""
    from manhwatok.app import container
    from manhwatok.app.chapter_post import build_chapter_post

    settings = Settings()
    try:
        tools = _tools(settings)
        with container.build_store(settings) as store:
            manhwa, chapter_tools, _ = _chapter_parts(settings, store, title, language, source)
            post, slides = build_chapter_post(
                manhwa,
                tools,
                chapter_tools,
                _account(store, account),
                datetime.now(timezone.utc),
                number=number,
                part=part,
                language=language,
                title=title_text,
                hashtags=hashtags,
                accent=accent,
                emojis=emojis,
            )
            for reader in chapter_tools.sources.values():
                _close(reader)
    except ManhwatokError as e:
        _fail(e)
    _progress.close()
    where = post.chapter
    typer.echo(
        f"post {post.id} · {where.source.value} chapter {where.number} "
        f"part {where.part}/{where.parts} · {len(slides)} slides → "
        f"{tools.posts.folder(post.id)}"
    )
    typer.echo(f"export with: manhwatok export {post.id}")


# --- the posting plan ------------------------------------------------------------------------

plan_app = typer.Typer(
    help="The posting plan: each account's slots over the days ahead and the posts in them.",
    no_args_is_help=True,
)
app.add_typer(plan_app, name="plan")

PLAN_ACCOUNT = typer.Option(
    None, "--account", "-a", help="Only this account (default: every account)."
)
NO_SLOTS = (
    'give an account slots with: manhwatok account set <handle> --slots "mon 19:00,thu 19:00"'
)


@plan_app.command("show")
def plan_show(
    account: Optional[str] = PLAN_ACCOUNT,
    days: int = typer.Option(7, "--days", min=1, max=60, help="How many days ahead."),
) -> None:
    """The slots of the days ahead, by day, each with the post going out then or `— empty`.

    Times are in each account's time zone. A post scheduled at a time that isn't one of its
    account's slots is listed too, marked `(not a slot)`."""
    from manhwatok.app import container
    from manhwatok.app.fill_plan import plan_rows

    settings = Settings()
    try:
        with container.build_store(settings) as store:
            accounts = [_account(store, account)] if account else store.accounts.list()
        posts = container.build_posts(settings)
        rows = plan_rows(accounts, posts.list(), _now(), days)
        lines = _plan_lines(rows, posts)
    except ManhwatokError as e:
        _fail(e)
    if not lines:
        typer.echo(f"nothing planned in the next {days} days — {NO_SLOTS}")
    for line in lines:
        typer.echo(line)


def _plan_lines(rows, posts) -> list[str]:
    """`plan show`'s table: a line per day, then a line per row under it."""
    from manhwatok.domain.text import plain_title
    from manhwatok.tui.text import post_status

    if not rows:
        return []
    width = max(len(row.account.display) for row in rows)
    titles = {
        row.post.id: plain_title(row.post.title) or "(untitled)" for row in rows if row.post
    }
    title_width = max(map(len, titles.values()), default=0)
    lines, day = [], None
    for row in rows:
        if row.at.date() != day:
            day = row.at.date()
            lines.append(f"{row.at:%a %d %b}")
        start = f"  {row.at:%H:%M}  {row.account.display:<{width}}"
        if row.post is None:
            lines.append(f"{start}  — empty")
            continue
        status = post_status(row.post, posts)
        line = f"{start}  {row.post.id}  {titles[row.post.id]:<{title_width}}  {status}"
        lines.append(line + ("" if row.on_slot else "  (not a slot)"))
    return lines


@plan_app.command("fill")
def plan_fill(
    account: Optional[str] = typer.Option(
        None, "--account", "-a", help="Only this account (default: every account with slots)."
    ),
    days: int = typer.Option(
        7, "--days", help="How many days ahead, 1–10 (TikTok schedules at most 10 days out)."
    ),
) -> None:
    """Make a post for each empty slot of the days ahead, as `next` makes them, and schedule
    it there.

    Running it again makes nothing new, and a sent post keeps its slot. It stops at the first
    failure; the posts made before it stay made and scheduled."""
    from manhwatok.app.context import open_context
    from manhwatok.app.fill_plan import fill
    from manhwatok.domain.account import normalize_handle

    settings = Settings()
    now = _now()
    try:
        ctx = open_context(settings, _progress)
        try:
            handles = (
                [account] if account else [a.handle for a in ctx.store.accounts.list() if a.slots]
            )
            if not handles:
                typer.echo(f"no account has slots yet — {NO_SLOTS}")
                return
            for handle in handles:
                made = fill(
                    ctx, handle, now, days, _warn, lambda p: _echo_filled(p, ctx.tools.posts)
                )
                if not made:
                    typer.echo(
                        f"every slot of @{normalize_handle(handle)} in the next {days} days "
                        "has a post"
                    )
        finally:
            ctx.close()
    except ManhwatokError as e:
        _fail(e)
    typer.echo("see the plan with `manhwatok plan show`; review the posts in `manhwatok tui`")


def _echo_filled(post, posts) -> None:
    _progress.close()
    typer.echo(
        f"{post.scheduled_at:%a %d %b %H:%M}  @{post.account}  post {post.id} · "
        f"{_next_summary(post, posts)}"
    )


@app.command()
def schedule(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    when: Optional[str] = typer.Argument(
        None,
        help='"YYYY-MM-DD HH:MM", or "<day> HH:MM" (mon..sun or daily) for the next such time, '
        "in the post's account's time zone (Europe/Paris without one).",
    ),
    clear: bool = typer.Option(False, "--clear", help="Unschedule the post."),
) -> None:
    """Set when a post goes out, e.g. `schedule 20260922-a3f9 "thu 19:00"`, or --clear it.

    The time is the post's place in `plan show`; a post scheduled at one of its account's slots
    takes that slot, so `plan fill` leaves it alone."""
    from manhwatok.app import container
    from manhwatok.app.fill_plan import schedule_post

    if (when is None) != clear:
        _fail(ManhwatokError("give a time or --clear" + (", not both" if clear else "")))
    settings = Settings()
    try:
        with container.build_store(settings) as store:
            post = schedule_post(
                container.build_posts(settings), store.accounts, post_id, when, _now()
            )
    except ManhwatokError as e:
        _fail(e)
    at = post.scheduled_at
    if at is None:
        typer.echo(f"post {post.id} is no longer scheduled")
    else:
        zone = getattr(at.tzinfo, "key", None) or f"{at:%Z}"
        typer.echo(f"post {post.id} goes out {at:%a %d %b %Y %H:%M} ({zone})")


@app.command("visibility")
def visibility_cmd(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    who: Optional[Visibility] = typer.Argument(
        None, help="everyone, friends (followers you follow back) or private (only you)."
    ),
    clear: bool = typer.Option(
        False, "--clear", help="Leave it to the account's own --visibility again."
    ),
) -> None:
    """Choose who can see a post once it is up, e.g. `visibility 20260922-a3f9 friends`.

    It sticks to the post, so every upload of it — here, in the Posts tab or from the Queue —
    shows it to the same people. Without one, the post's account decides (`account set
    --visibility`), and `upload --visibility` beats both for one upload."""
    from manhwatok.app import container
    from manhwatok.app.upload_post import set_visibility

    if (who is None) != clear:
        _fail(ManhwatokError("give a visibility or --clear" + (", not both" if clear else "")))
    try:
        post = set_visibility(container.build_posts(Settings()), post_id, who)
    except ManhwatokError as e:
        _fail(e)
    if post.visibility is None:
        typer.echo(f"post {post.id} follows its account's choice")
    else:
        typer.echo(f"post {post.id} is visible to {post.visibility.spoken}")
