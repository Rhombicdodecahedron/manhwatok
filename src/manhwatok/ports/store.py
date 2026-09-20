from datetime import datetime
from typing import Protocol

from manhwatok.domain.account import Account
from manhwatok.domain.chapter import ChapterRecord, PartRecord
from manhwatok.domain.models import ChapterSourceName
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
        """Idempotent: re-recording a post keeps the later of the two dates."""
        ...

    def recent(self, account: str, since: datetime) -> set[int]:
        """AniList ids this account exported at or after `since`."""
        ...


class ChapterRepository(Protocol):
    """What each title's chapters are, and which parts of them were built and published."""

    def record_chapters(self, rows: list[ChapterRecord]) -> None:
        """Upsert what the source listed, keeping each chapter's download date."""
        ...

    def chapters(
        self,
        anilist_id: int,
        language: str = "en",
        source: ChapterSourceName = ChapterSourceName.MANGADEX,
    ) -> list[ChapterRecord]: ...

    def sources_of(self, anilist_id: int, language: str = "en") -> list[ChapterSourceName]:
        """Which sources this title's chapters came from; a title sticks to one."""
        ...

    def mark_downloaded(
        self,
        anilist_id: int,
        number: str,
        language: str,
        when: datetime,
        source: ChapterSourceName = ChapterSourceName.MANGADEX,
    ) -> None: ...

    def record_part(self, part: PartRecord) -> None:
        """Idempotent per part; rebuilding one replaces the post that carries it."""
        ...

    def parts(
        self,
        anilist_id: int,
        language: str = "en",
        source: ChapterSourceName = ChapterSourceName.MANGADEX,
    ) -> list[PartRecord]: ...

    def mark_published(self, post_id: str, when: datetime) -> None:
        """Stamp every part this post carries; the first date wins."""
        ...

    def forget_parts(self, post_id: str) -> None: ...

    def titles(self) -> list[tuple[int, str]]: ...
