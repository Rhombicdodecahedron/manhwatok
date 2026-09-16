"""Create and change accounts and themes. Everything is validated before AniList is asked
about genre/tag names, and names are saved in AniList's spelling."""

from __future__ import annotations

from typing import Any

from manhwatok.app.names import NameCheck
from manhwatok.domain.account import Account, normalize_handle
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Sort
from manhwatok.domain.theme import Theme, normalize_theme_name
from manhwatok.ports.store import AccountRepository, ThemeRepository


def _checked_account(account: Account, names: NameCheck, given: dict[str, Any]) -> Account:
    """Check only the name lists that were just given (an update may not touch them)."""
    update: dict[str, list[str]] = {}
    for field in ("genres", "block_genres"):
        if field in given:
            update[field] = names.genres(getattr(account, field))
    if "block_tags" in given:
        update["block_tags"] = names.tags(account.block_tags)
    return account.model_copy(update=update)


def add_account(
    accounts: AccountRepository, names: NameCheck, handle: str, fields: dict[str, Any]
) -> Account:
    """`fields`: any Account fields besides the handle; the rest keep their defaults."""
    account = _checked_account(Account(handle=handle, **fields), names, fields)
    accounts.add(account)
    return account


def update_account(
    accounts: AccountRepository, names: NameCheck, handle: str, changes: dict[str, Any]
) -> Account:
    """Change only the fields in `changes`; raises AccountNotFound."""
    if not changes:
        raise ManhwatokError(
            "nothing to change — give at least one option (see `manhwatok account set --help`)"
        )
    current = accounts.get(normalize_handle(handle))
    account = Account.model_validate({**current.model_dump(), **changes})
    account = _checked_account(account, names, changes)
    accounts.update(account)
    return account


def add_theme(
    themes: ThemeRepository,
    names: NameCheck,
    name: str,
    tags: list[str],
    genres: list[str],
    sort: Sort,
    min_tag_rank: int,
    title: str,
) -> Theme:
    theme = Theme(
        name=name, tags=tags, genres=genres, sort=sort, min_tag_rank=min_tag_rank, title=title
    )
    theme = theme.model_copy(
        update={"tags": names.tags(theme.tags), "genres": names.genres(theme.genres)}
    )
    themes.add(theme)
    return theme


def update_theme(
    themes: ThemeRepository, names: NameCheck, name: str, changes: dict[str, Any]
) -> Theme:
    """Change only the fields in `changes` (not the name); raises ThemeNotFound."""
    current = themes.get(normalize_theme_name(name))
    theme = Theme.model_validate({**current.model_dump(), **changes, "name": current.name})
    update: dict[str, list[str]] = {}
    if "tags" in changes:
        update["tags"] = names.tags(theme.tags)
    if "genres" in changes:
        update["genres"] = names.genres(theme.genres)
    theme = theme.model_copy(update=update)
    themes.update(theme)
    return theme
