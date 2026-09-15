class ManhwatokError(Exception):
    """Base for expected, user-facing failures."""


class MetadataError(ManhwatokError):
    """A metadata source (AniList, MangaUpdates) failed or returned something unusable."""


class CacheError(ManhwatokError):
    """The on-disk cache (SQLite) is unusable: unwritable data dir, locked or corrupt DB."""


class DraftError(ManhwatokError):
    """The edited draft file can't be turned into a post (bad line, no title, no items)."""


class PostNotFound(ManhwatokError):
    """No saved post with that id."""


class NotRendered(ManhwatokError):
    """The post has no slides yet; run `manhwatok render <id>` first."""


class StorageError(ManhwatokError):
    """Reading or writing post files failed (permissions, disk, bad encoding)."""


class AccountNotFound(ManhwatokError):
    """No saved account with that handle."""


class ThemeNotFound(ManhwatokError):
    """No saved theme with that name."""


class InvalidName(ManhwatokError):
    """A handle, theme name, genre, tag or accent colour is not acceptable."""


class AlreadyExists(ManhwatokError):
    """An account or theme with that handle/name is already saved."""


class UploadUnavailable(ManhwatokError):
    """The upload extra (Playwright) or its Chromium isn't installed."""


class NotLoggedIn(ManhwatokError):
    """TikTok sent the account's browser profile to its login page."""
