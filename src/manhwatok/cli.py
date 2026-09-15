from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn, Optional

import typer

from manhwatok.config import Settings
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import SearchQuery, Sort
from manhwatok.domain.post import DEFAULT_ACCENT, DEFAULT_HASHTAGS

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


# Search options shared by `suggest` and `build`.
TAG = typer.Option(
    None, "--tag", "-t", help="AniList tag; repeat to require several (see `manhwatok tags`)."
)
GENRE = typer.Option(None, "--genre", "-g", help="AniList genre; repeat to require several.")
SORT = typer.Option(Sort.SCORE, help="Ranking order.")
LIMIT = typer.Option(12, "--limit", "-n", min=1, max=50, help="How many titles.")
MIN_TAG_RANK = typer.Option(
    60, min=0, max=100, help="Ignore titles where the tag is weaker than this rank."
)
CHAPTERS = typer.Option(
    True, "--chapters/--no-chapters", help="Look up missing chapter counts on MangaUpdates."
)


def _query(
    tag: Optional[list[str]], genre: Optional[list[str]], sort: Sort, limit: int, min_tag_rank: int
) -> SearchQuery:
    if not tag and not genre:
        _fail(ValueError("give at least one --tag or --genre"))
    return SearchQuery(
        tags=tag or [], genres=genre or [], sort=sort, limit=limit, min_tag_rank=min_tag_rank
    )


@app.command()
def suggest(
    tag: Optional[list[str]] = TAG,
    genre: Optional[list[str]] = GENRE,
    sort: Sort = SORT,
    limit: int = LIMIT,
    min_tag_rank: int = MIN_TAG_RANK,
    chapters: bool = CHAPTERS,
) -> None:
    """Suggest top Korean manhwa matching tags/genres."""
    from manhwatok.app import container
    from manhwatok.app.suggest import suggest_titles
    from manhwatok.domain.labels import chapter_label

    query = _query(tag, genre, sort, limit, min_tag_rank)
    settings = Settings()
    try:
        with container.build_store(settings) as store:
            results = suggest_titles(
                query,
                container.build_metadata(settings),
                container.build_chapter_source(settings, store.cache) if chapters else None,
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
    tag: Optional[list[str]] = TAG,
    genre: Optional[list[str]] = GENRE,
    sort: Sort = SORT,
    limit: int = LIMIT,
    min_tag_rank: int = MIN_TAG_RANK,
    chapters: bool = CHAPTERS,
    title: str = typer.Option("", help="Post title; wrap words in *stars* to colour them."),
    hashtags: str = typer.Option(DEFAULT_HASHTAGS, help="Hashtags appended to the caption."),
    accent: str = typer.Option(DEFAULT_ACCENT, help="Accent colour for cover and end slides."),
) -> None:
    """Build a post: pick titles and hooks in your editor, then render the slides."""
    from manhwatok.app import container
    from manhwatok.app.build_post import build_post

    query = _query(tag, genre, sort, limit, min_tag_rank)
    settings = Settings()
    try:
        tools = _tools(settings)
        with container.build_store(settings) as store:
            built = build_post(
                query,
                title,
                hashtags,
                accent,
                container.build_metadata(settings),
                container.build_chapter_source(settings, store.cache) if chapters else None,
                tools,
                now=datetime.now(timezone.utc),
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
    """Copy a post's slides and caption.txt to a folder for uploading."""
    from manhwatok.app.export_post import export_post

    settings = Settings()
    try:
        dest = export_post(post_id, _tools(settings).posts, out or settings.export_dir)
    except ManhwatokError as e:
        _fail(e)
    typer.echo(f"exported → {dest}")


@app.command()
def posts() -> None:
    """List saved posts, newest first."""
    from manhwatok.domain.text import plain_title

    try:
        saved = _tools(Settings()).posts.list()
    except ManhwatokError as e:
        _fail(e)
    if not saved:
        typer.echo("no posts yet — try: manhwatok build -t Revenge")
        return
    for post in saved:
        when = post.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
        size = "draft" if post.is_unfinished else f"{post.slide_count} slides"
        typer.echo(f"{post.id}  {when}  {size:>9}  {plain_title(post.title) or '(untitled)'}")
