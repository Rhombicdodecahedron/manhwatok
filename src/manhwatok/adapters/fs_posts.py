"""Posts on disk: one folder per post with post.json, draft.txt (while broken), slides, caption."""

from __future__ import annotations

import re
import secrets
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from manhwatok.domain.errors import PostNotFound
from manhwatok.domain.post import ListPost

POST_FILE = "post.json"
DRAFT_FILE = "draft.txt"
_ID = re.compile(r"^\d{8}-[0-9a-f]{4}$")


class FsPostRepository:
    def __init__(self, posts_dir: Path) -> None:
        self._dir = posts_dir

    def new_id(self, today: date) -> str:
        while True:
            post_id = f"{today:%Y%m%d}-{secrets.token_hex(2)}"
            if not (self._dir / post_id).exists():
                return post_id

    def folder(self, post_id: str) -> Path:
        if not _ID.match(post_id):
            raise PostNotFound(f"{post_id!r} is not a post id (like 20260914-a3f9)")
        return self._dir / post_id

    def save(self, post: ListPost) -> None:
        folder = self.folder(post.id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / POST_FILE).write_text(post.model_dump_json(indent=2), encoding="utf-8")

    def get(self, post_id: str) -> ListPost:
        path = self.folder(post_id) / POST_FILE
        if not path.is_file():
            raise PostNotFound(f"no post {post_id} — see `manhwatok posts`")
        try:
            return ListPost.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as e:
            raise PostNotFound(
                f"post {post_id} is unreadable: {e.error_count()} invalid fields"
            ) from e

    def list(self) -> list[ListPost]:
        posts = []
        for path in self._dir.glob(f"*/{POST_FILE}") if self._dir.is_dir() else []:
            try:
                posts.append(ListPost.model_validate_json(path.read_text(encoding="utf-8")))
            except ValidationError:
                continue  # a corrupt folder shouldn't hide the others
        return sorted(posts, key=lambda p: p.created_at, reverse=True)

    def save_draft(self, post_id: str, text: str) -> None:
        folder = self.folder(post_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / DRAFT_FILE).write_text(text, encoding="utf-8")

    def load_draft(self, post_id: str) -> str | None:
        path = self.folder(post_id) / DRAFT_FILE
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def clear_draft(self, post_id: str) -> None:
        (self.folder(post_id) / DRAFT_FILE).unlink(missing_ok=True)
