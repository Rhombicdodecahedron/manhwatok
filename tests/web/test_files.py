import os

import pytest

pytest.importorskip("fastapi")

from manhwatok.app.render_post import render_post  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import post  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402

PID = "20260914-0002"


def _rendered(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.tools.posts.save(post(id=PID))
    render_post(PID, ctx.tools)
    return ctx


def test_a_slide_is_served(tmp_path):
    with client_for(_rendered(tmp_path)) as client:
        response = client.get(f"/files/{PID}/01.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


@pytest.mark.parametrize(
    "url",
    [
        f"/files/{PID}/caption.txt",  # not a picture
        f"/files/{PID}/99.png",  # not there
        "/files/20260101-0000/01.png",  # no such post
        f"/files/{PID}/..%2Fpost.json",
        "/files/..%2F..%2Fetc/passwd.png",
        f"/files/{PID}/.hidden.png",
    ],
)
def test_nothing_else_is_served(tmp_path, url):
    with client_for(_rendered(tmp_path)) as client:
        assert client.get(url).status_code == 404


def test_a_link_inside_a_post_folder_is_not_followed(tmp_path):
    ctx = _rendered(tmp_path)
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"\x89PNG secret")
    os.symlink(outside, ctx.tools.posts.folder(PID) / "link.png")
    with client_for(ctx) as client:
        assert client.get(f"/files/{PID}/link.png").status_code == 404
