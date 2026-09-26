import pytest

pytest.importorskip("fastapi")

from tests.tui.helpers import make_ctx  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402


def test_the_slides_font_is_served_for_the_pages(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        response = client.get("/fonts/Montserrat-Variable.ttf")
    assert response.status_code == 200
    assert len(response.content) > 100_000


def test_the_shell_has_the_sidebar_and_the_mode_switch(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        html = client.get("/posts").text
    assert '<nav class="sidebar"' in html
    assert '<a href="/posts" aria-current="page"' in html
    assert '<a href="/new"' in html
    assert 'hx-post="/mode"' in html and 'id="header"' in html


def test_the_stylesheet_uses_the_font_and_the_palette(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        css = client.get("/static/app.css").text
    assert "Montserrat-Variable.ttf" in css
    for token in ("--gutter: #1c1a24", "--paper: #efe9dd", "--accent: #43c9e4"):
        assert token in css
