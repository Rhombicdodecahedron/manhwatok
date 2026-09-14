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
