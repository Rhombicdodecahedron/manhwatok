from datetime import datetime
from typing import Protocol

from manhwatok.domain.account import Account
from manhwatok.domain.theme import Theme


class AccountRepository(Protocol):
    def add(self, account: Account) -> None:
        """Raises AlreadyExists if the handle is taken."""
        ...

    def update(self, account: Account) -> None:
        """Replaces the saved account with the same handle; raises AccountNotFound."""
        ...

    def get(self, handle: str) -> Account: ...

    def list(self) -> list[Account]: ...

    def remove(self, handle: str) -> None: ...


class ThemeRepository(Protocol):
    def add(self, theme: Theme) -> None: ...

    def update(self, theme: Theme) -> None: ...

    def get(self, name: str) -> Theme: ...

    def list(self) -> list[Theme]: ...

    def remove(self, name: str) -> None: ...


class HistoryRepository(Protocol):
    def record(
        self, account: str, post_id: str, anilist_ids: list[int], exported_at: datetime
    ) -> None:
        """Idempotent: re-recording a post keeps its first date."""
        ...

    def recent(self, account: str, since: datetime) -> set[int]:
        """AniList ids this account exported at or after `since`."""
        ...
