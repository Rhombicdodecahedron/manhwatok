import re
from datetime import date, datetime, timezone

import pytest

from manhwatok.adapters.fs_posts import FsPostRepository
from manhwatok.domain.errors import PostNotFound, StorageError
from tests.unit.fakes import post


def test_new_id_is_date_plus_hex_and_unique(tmp_path):
    repo = FsPostRepository(tmp_path)
    ids = {repo.new_id(date(2026, 9, 14)) for _ in range(20)}
    assert all(re.fullmatch(r"20260914-[0-9a-f]{4}", i) for i in ids)


def test_new_id_reserves_its_folder(tmp_path):
    repo = FsPostRepository(tmp_path / "posts")
    post_id = repo.new_id(date(2026, 9, 14))
    assert (tmp_path / "posts" / post_id).is_dir()


def test_new_id_blocked_posts_dir_raises_storage_error(tmp_path):
    (tmp_path / "posts").write_bytes(b"not a directory")
    with pytest.raises(StorageError):
        FsPostRepository(tmp_path / "posts").new_id(date(2026, 9, 14))


def test_new_id_skips_existing_folders(tmp_path, monkeypatch):
    (tmp_path / "20260914-aaaa").mkdir()
    tokens = iter(["aaaa", "bbbb"])
    monkeypatch.setattr("manhwatok.adapters.fs_posts.secrets.token_hex", lambda n: next(tokens))
    assert FsPostRepository(tmp_path).new_id(date(2026, 9, 14)) == "20260914-bbbb"


def test_save_blocked_by_a_file_raises_storage_error(tmp_path):
    (tmp_path / "20260914-a3f9").write_bytes(b"not a directory")
    with pytest.raises(StorageError):
        FsPostRepository(tmp_path).save(post())


def test_save_get_round_trip(tmp_path):
    repo = FsPostRepository(tmp_path)
    repo.save(post())
    assert repo.get("20260914-a3f9") == post()
    assert (tmp_path / "20260914-a3f9" / "post.json").is_file()


def test_get_missing_post(tmp_path):
    with pytest.raises(PostNotFound, match="no post 20260914-0000"):
        FsPostRepository(tmp_path).get("20260914-0000")


@pytest.mark.parametrize(
    "bad", ["../etc", "x", "20260914-A3F9", "20260914-a3f9/..", "20260914-a3f9\n"]
)
def test_malformed_ids_never_touch_the_filesystem(tmp_path, bad):
    with pytest.raises(PostNotFound, match="not a post id"):
        FsPostRepository(tmp_path).folder(bad)


def test_corrupt_post_json(tmp_path):
    folder = tmp_path / "20260914-a3f9"
    folder.mkdir()
    (folder / "post.json").write_text('{"id": 3}')
    with pytest.raises(PostNotFound, match="unreadable"):
        FsPostRepository(tmp_path).get("20260914-a3f9")


def test_list_newest_first_and_skips_corrupt(tmp_path):
    repo = FsPostRepository(tmp_path)
    repo.save(post(id="20260913-0001", created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    repo.save(post(id="20260914-0002", created_at=datetime(2026, 9, 14, tzinfo=timezone.utc)))
    (tmp_path / "20260914-0003").mkdir()
    (tmp_path / "20260914-0003" / "post.json").write_text("garbage")
    assert [p.id for p in repo.list()] == ["20260914-0002", "20260913-0001"]


def test_list_without_posts_dir(tmp_path):
    assert FsPostRepository(tmp_path / "missing").list() == []


def test_list_skips_undecodable_post_json(tmp_path):
    repo = FsPostRepository(tmp_path)
    repo.save(post())
    bad = tmp_path / "20260914-bad1"
    bad.mkdir()
    (bad / "post.json").write_bytes(b"\xff\xfe\x00\x01")
    assert [p.id for p in repo.list()] == ["20260914-a3f9"]


def test_get_undecodable_post_json_raises_storage_error(tmp_path):
    folder = tmp_path / "20260914-bad1"
    folder.mkdir()
    (folder / "post.json").write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(StorageError):
        FsPostRepository(tmp_path).get("20260914-bad1")


def test_draft_save_load_clear(tmp_path):
    repo = FsPostRepository(tmp_path)
    assert repo.load_draft("20260914-a3f9") is None
    repo.save_draft("20260914-a3f9", "title: x\n")
    assert repo.load_draft("20260914-a3f9") == "title: x\n"
    repo.clear_draft("20260914-a3f9")
    repo.clear_draft("20260914-a3f9")  # idempotent
    assert repo.load_draft("20260914-a3f9") is None


# --- noticing changes made from elsewhere -------------------------------------------------------


def test_the_stamp_stays_the_same_while_nothing_changes(tmp_path):
    repo = FsPostRepository(tmp_path)
    repo.save(post(id="20260914-0001"))
    assert repo.stamp() == repo.stamp()


def test_the_stamp_changes_when_a_post_is_added_saved_or_deleted(tmp_path):
    import os
    import shutil

    repo = FsPostRepository(tmp_path)
    before = repo.stamp()
    repo.save(post(id="20260914-0001"))
    added = repo.stamp()
    assert added != before
    path = repo.folder("20260914-0001") / "post.json"
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
    assert repo.stamp() != added
    shutil.rmtree(repo.folder("20260914-0001"))
    assert repo.stamp() == before


def test_the_stamp_changes_when_a_slide_is_written_over_in_place(tmp_path):
    import os

    repo = FsPostRepository(tmp_path)
    repo.save(post(id="20260914-0001"))
    slide = repo.folder("20260914-0001") / "01.png"
    slide.write_bytes(b"old")
    (repo.folder("20260914-0001") / "02.png").write_bytes(b"written after")
    before = repo.stamp()
    slide.write_bytes(b"new")
    os.utime(slide, ns=(slide.stat().st_atime_ns, slide.stat().st_mtime_ns + 1_000_000))
    assert repo.stamp() != before


def test_the_stamp_of_no_posts_folder_is_empty(tmp_path):
    assert FsPostRepository(tmp_path / "none").stamp() == ()
