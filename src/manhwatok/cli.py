from __future__ import annotations

from typing import NoReturn

import typer

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
