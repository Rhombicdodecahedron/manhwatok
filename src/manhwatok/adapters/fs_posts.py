"""Posts on disk: one folder per post with post.json, draft.txt (while broken), slides, caption."""

from __future__ import annotations

import os
import re
import secrets
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from manhwatok.domain.errors import PostNotFound, StorageError
from manhwatok.domain.post import ListPost

POST_FILE = "post.json"
DRAFT_FILE = "draft.txt"
_ID = re.compile(r"^\d{8}-[0-9a-f]{4}$")


class FsPostRepository:
    def __init__(self, posts_dir: Path) -> None:
        self._dir = posts_dir

    def new_id(self, today: date) -> str:
        """A fresh id whose folder is created right here, so two builds can't both get it."""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            while True:
                post_id = f"{today:%Y%m%d}-{secrets.token_hex(2)}"
                try:
                    (self._dir / post_id).mkdir()
                    return post_id
                except FileExistsError:
                    continue
        except OSError as e:
            raise StorageError(f"could not create a post folder in {self._dir}: {e}") from e

    def folder(self, post_id: str) -> Path:
        if not _ID.fullmatch(post_id):
            raise PostNotFound(f"{post_id!r} is not a post id (like 20260914-a3f9)")
        return self._dir / post_id

    def save(self, post: ListPost) -> None:
        folder = self.folder(post.id)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / POST_FILE).write_text(post.model_dump_json(indent=2), encoding="utf-8")
        except OSError as e:
            raise StorageError(f"could not save post {post.id}: {e}") from e

    def get(self, post_id: str) -> ListPost:
        path = self.folder(post_id) / POST_FILE
        if not path.is_file():
            raise PostNotFound(f"no post {post_id} — see `manhwatok posts`")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise StorageError(f"could not read post {post_id}: {e}") from e
        except UnicodeDecodeError as e:
            raise StorageError(f"post {post_id} is not valid UTF-8: {e}") from e
        try:
            return ListPost.model_validate_json(text)
        except ValidationError as e:
            raise PostNotFound(
                f"post {post_id} is unreadable: {e.error_count()} invalid fields"
            ) from e

    def list(self) -> list[ListPost]:
        posts = []
        for path in self._dir.glob(f"*/{POST_FILE}") if self._dir.is_dir() else []:
            try:
                text = path.read_text(encoding="utf-8")
                posts.append(ListPost.model_validate_json(text))
            except (ValidationError, OSError, UnicodeDecodeError):
                continue  # a corrupt or unreadable folder shouldn't hide the others
        return sorted(posts, key=lambda p: p.created_at, reverse=True)

    def stamp(self) -> tuple:
        """A fingerprint of every post on disk, cheap to take: it changes when a post is added,
        saved, deleted or rendered again (by this process or any other), so a screen that shows
        posts can tell when to read them again."""
        if not self._dir.is_dir():
            return ()
        marks = []
        for folder in sorted(self._dir.iterdir(), key=lambda p: p.name):
            if not _ID.fullmatch(folder.name):
                continue
            try:
                with os.scandir(folder) as entries:
                    times = [e.stat().st_mtime_ns for e in entries if e.is_file()]
                # every file's time counts: one slide written over changes the sum
                marks.append((folder.name, folder.stat().st_mtime_ns, len(times), sum(times)))
            except OSError:
                continue  # removed while looking: the next stamp will say so
        return tuple(marks)

    def save_draft(self, post_id: str, text: str) -> None:
        folder = self.folder(post_id)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / DRAFT_FILE).write_text(text, encoding="utf-8")
        except OSError as e:
            raise StorageError(f"could not save draft for {post_id}: {e}") from e

    def load_draft(self, post_id: str) -> str | None:
        path = self.folder(post_id) / DRAFT_FILE
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            raise StorageError(f"could not read draft for {post_id}: {e}") from e
        except UnicodeDecodeError as e:
            raise StorageError(f"draft for {post_id} is not valid UTF-8: {e}") from e

    def clear_draft(self, post_id: str) -> None:
        try:
            (self.folder(post_id) / DRAFT_FILE).unlink(missing_ok=True)
        except OSError as e:
            raise StorageError(f"could not clear draft for {post_id}: {e}") from e
