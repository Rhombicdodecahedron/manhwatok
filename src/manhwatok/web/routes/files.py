"""A post's pictures (slides, cover versions, art) for the page. Only plain picture names
straight inside a post's own folder, never a link: nothing else on the disk is reachable."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from manhwatok.web.routes.common import ctx_of

router = APIRouter()

POST_ID = re.compile(r"^[0-9A-Za-z_-]+$")
PICTURE = re.compile(r"^[0-9A-Za-z_-][0-9A-Za-z_.-]*\.(png|jpe?g|webp)$")


def file_url(path: Path) -> str:
    """The URL of a picture in a post's folder; its mtime in the URL lets the browser keep it
    until a render redraws it."""
    return f"/files/{path.parent.name}/{path.name}?v={path.stat().st_mtime_ns}"


@router.get("/files/{post_id}/{name}")
def post_file(request: Request, post_id: str, name: str) -> FileResponse:
    if not POST_ID.match(post_id) or not PICTURE.match(name) or ".." in name:
        raise HTTPException(404)
    folder = ctx_of(request).tools.posts.folder(post_id)
    path = folder / name
    if folder.is_symlink() or path.is_symlink() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})
