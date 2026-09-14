from manhwatok.adapters.sqlite_cache import SqliteCache


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_miss_returns_none(tmp_path):
    assert SqliteCache(tmp_path / "c.db").get("k", 60) is None


def test_put_then_get(tmp_path):
    cache = SqliteCache(tmp_path / "c.db")
    cache.put("k", "v")
    assert cache.get("k", 60) == "v"


def test_expired_entry_is_a_miss(tmp_path):
    clock = Clock()
    cache = SqliteCache(tmp_path / "c.db", clock=clock)
    cache.put("k", "v")
    clock.now += 61
    assert cache.get("k", 60) is None


def test_put_overwrites_and_refreshes_age(tmp_path):
    clock = Clock()
    cache = SqliteCache(tmp_path / "c.db", clock=clock)
    cache.put("k", "old")
    clock.now += 50
    cache.put("k", "new")
    clock.now += 50
    assert cache.get("k", 60) == "new"


def test_persists_across_instances_and_creates_parent_dirs(tmp_path):
    path = tmp_path / "a" / "b" / "c.db"
    SqliteCache(path).put("k", "v")
    assert SqliteCache(path).get("k", 60) == "v"
