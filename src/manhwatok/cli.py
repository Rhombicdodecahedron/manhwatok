from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn, Optional

import typer

from manhwatok.config import Settings
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import SearchQuery, Sort

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
    accent: Optional[str] = typer.Option(
        None, help="Accent colour for cover and end slides (default: the account's, else #43c9e4)."
    ),
) -> None:
    """Build a post: pick titles and hooks in your editor, then render the slides."""
    from manhwatok.app import container
    from manhwatok.app.build_post import build_post
    from manhwatok.app.suggest import suggest_for_account

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
    """List saved posts, newest first."""
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
    for post in saved:
        when = post.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
        size = "draft" if post.is_unfinished else f"{post.slide_count} slides"
        title = plain_title(post.title) or "(untitled)"
        typer.echo(f"{post.id}  {when}  {who[post.id]:<{width}}  {size:>9}  {title}")


@app.command()
def delete(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for confirmation."),
) -> None:
    """Delete a post's folder. An exported post's titles still count as posted."""
    from manhwatok.app import container
    from manhwatok.app.delete_post import delete_post, leftover_state
    from manhwatok.domain.errors import PostNotFound

    try:
        repo = container.build_posts(Settings())
        try:
            post = repo.get(post_id)
            size = "draft" if post.is_unfinished else f"{post.slide_count} slides"
        except PostNotFound:
            size = leftover_state(post_id, repo)  # an empty or broken folder can still go
        if not yes and not typer.confirm(f"Delete post {post_id} ({size})?", default=False):
            typer.echo("kept")
            return
        delete_post(post_id, repo)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"deleted post {post_id}")


# --- assisted upload -----------------------------------------------------------------------


def _ask(question: str) -> bool:
    """A yes/no question that defaults to no; no answer at all (Ctrl-D, Ctrl-C) is a no too."""
    try:
        return typer.confirm(question, default=False)
    except typer.Abort:
        typer.echo()
        return False


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
    typer.echo(f"browser closed — once logged in, `manhwatok upload` posts as {account.display}")


@app.command()
def upload(
    post_id: str = typer.Argument(..., help="Post id, see `manhwatok posts`."),
    debug: bool = typer.Option(
        False, "--debug", help="Save a screenshot and the page's HTML if something isn't found."
    ),
) -> None:
    """Open TikTok's upload page as the post's account with the slides and caption filled in.
    You check it and click Post yourself, then answer y here to record the post as sent."""
    from manhwatok.app import container
    from manhwatok.app.upload_post import upload_post

    settings = Settings()
    try:
        with container.build_store(settings) as store:
            posted = upload_post(
                post_id,
                container.build_posts(settings),
                store.accounts,
                store.history,
                container.build_uploader(settings),
                _ask,
                typer.echo,
                now=datetime.now(timezone.utc),
                debug=debug,
            )
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"recorded post {post_id} as sent" if posted else "nothing recorded")


# --- accounts and themes -------------------------------------------------------------------

account_app = typer.Typer(
    help="TikTok accounts: genre filters, hashtags, accent, end-slide texts.",
    no_args_is_help=True,
)
theme_app = typer.Typer(
    help="Themes: reusable tags/genres + title, shared by every account.", no_args_is_help=True
)
app.add_typer(account_app, name="account")
app.add_typer(theme_app, name="theme")


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
ACCOUNT_ACCENT = typer.Option(None, "--accent", help="Accent colour, e.g. #43c9e4.")
CTA_TITLE = typer.Option(None, "--cta-title", help="End-slide title; *word* = accent colour.")
CTA_FOLLOW = typer.Option(None, "--cta-follow", help="End-slide follow line.")
REPEAT_DAYS = typer.Option(
    None, "--repeat-days", min=1, max=3650, help="Don't suggest titles exported this recently."
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
) -> dict:
    from manhwatok.domain.text import split_names

    lists = {"genres": genres, "block_genres": block_genres, "block_tags": block_tags}
    fields: dict = {k: split_names(v) for k, v in lists.items() if v is not None}
    scalars = {
        "hashtags": hashtags,
        "accent": accent,
        "cta_title": cta_title,
        "cta_follow": cta_follow,
        "repeat_days": repeat_days,
    }
    fields.update({k: v for k, v in scalars.items() if v is not None})
    return fields


def _print_account(a) -> None:
    typer.secho(a.display, bold=True)
    for label, value in [
        ("genres", ", ".join(a.genres) or "any"),
        ("block genres", ", ".join(a.block_genres) or "-"),
        ("block tags", ", ".join(a.block_tags) or "-"),
        ("hashtags", a.hashtags or "-"),
        ("accent", a.accent),
        ("cta title", a.cta_title),
        ("cta follow", a.cta_follow),
        ("repeat days", str(a.repeat_days)),
    ]:
        typer.echo(f"  {label:<13} {value}")


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
    accent: Optional[str] = ACCOUNT_ACCENT,
    cta_title: Optional[str] = CTA_TITLE,
    cta_follow: Optional[str] = CTA_FOLLOW,
    repeat_days: Optional[int] = REPEAT_DAYS,
) -> None:
    """Add an account; unset options get the defaults."""
    from manhwatok.app.accounts import add_account

    fields = _account_fields(
        genres, block_genres, block_tags, hashtags, accent, cta_title, cta_follow, repeat_days
    )
    _save_account(add_account, "added", handle, fields)


@account_app.command("set")
def account_set(
    handle: str = typer.Argument(..., help="TikTok handle, e.g. @manhwa.daily"),
    genres: Optional[str] = GENRES,
    block_genres: Optional[str] = BLOCK_GENRES,
    block_tags: Optional[str] = BLOCK_TAGS,
    hashtags: Optional[str] = ACCOUNT_HASHTAGS,
    accent: Optional[str] = ACCOUNT_ACCENT,
    cta_title: Optional[str] = CTA_TITLE,
    cta_follow: Optional[str] = CTA_FOLLOW,
    repeat_days: Optional[int] = REPEAT_DAYS,
) -> None:
    """Change an account; only the given options change."""
    from manhwatok.app.accounts import update_account

    fields = _account_fields(
        genres, block_genres, block_tags, hashtags, accent, cta_title, cta_follow, repeat_days
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
def account_remove(handle: str = typer.Argument(..., help="TikTok handle.")) -> None:
    """Remove an account. Its posting history is kept, so re-adding it keeps repeat protection."""
    from manhwatok.app import container
    from manhwatok.domain.account import normalize_handle

    try:
        with container.build_store(Settings()) as store:
            h = normalize_handle(handle)
            store.accounts.remove(h)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"removed @{h} (its posting history is kept)")


def _print_theme(t) -> None:
    typer.secho(t.name, bold=True)
    for label, value in [
        ("title", t.title),
        ("tags", ", ".join(t.tags) or "-"),
        ("genres", ", ".join(t.genres) or "-"),
        ("sort", t.sort.value),
        ("min tag rank", str(t.min_tag_rank)),
    ]:
        typer.echo(f"  {label:<13} {value}")


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
                store.themes, names, name, tag or [], genre or [], sort, min_tag_rank, title
            )
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"added theme {theme.name}")
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
