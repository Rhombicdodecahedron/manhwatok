class ManhwatokError(Exception):
    """Base for expected, user-facing failures."""


class MetadataError(ManhwatokError):
    """A metadata source (AniList, MangaUpdates) failed or returned something unusable."""


class CacheError(ManhwatokError):
    """The on-disk cache (SQLite) is unusable: unwritable data dir, locked or corrupt DB."""
