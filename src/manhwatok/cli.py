from __future__ import annotations

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


@app.command()
def suggest(
    tag: Optional[list[str]] = typer.Option(
        None, "--tag", "-t", help="AniList tag; repeat to require several (see `manhwatok tags`)."
    ),
    genre: Optional[list[str]] = typer.Option(
        None, "--genre", "-g", help="AniList genre; repeat to require several."
    ),
    sort: Sort = typer.Option(Sort.SCORE, help="Ranking order."),
    limit: int = typer.Option(12, "--limit", "-n", min=1, max=50, help="How many titles."),
    min_tag_rank: int = typer.Option(
        60, min=0, max=100, help="Ignore titles where the tag is weaker than this rank."
    ),
    chapters: bool = typer.Option(
        True, "--chapters/--no-chapters", help="Look up missing chapter counts on MangaUpdates."
    ),
) -> None:
    """Suggest top Korean manhwa matching tags/genres."""
    from manhwatok.app import container
    from manhwatok.app.suggest import suggest_titles
    from manhwatok.domain.labels import chapter_label

    if not tag and not genre:
        _fail(ValueError("give at least one --tag or --genre"))
    settings = Settings()
    query = SearchQuery(
        tags=tag or [], genres=genre or [], sort=sort, limit=limit, min_tag_rank=min_tag_rank
    )
    try:
        results = suggest_titles(
            query,
            container.build_metadata(settings),
            container.build_chapter_source(settings) if chapters else None,
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
