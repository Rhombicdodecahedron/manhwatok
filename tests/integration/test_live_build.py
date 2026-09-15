"""Build and render a real post from live AniList + covers.

Run with: MANHWATOK_LIVE=1 uv run pytest tests/integration/test_live_build.py -s
The rendered folder is printed so you can look at the PNGs.
"""

import os
from datetime import datetime, timezone

import pytest
from PIL import Image

from manhwatok.app.build_post import build_post
from manhwatok.app.container import (
    build_chapter_source,
    build_metadata,
    build_post_tools,
    build_store,
)
from manhwatok.app.suggest import suggest_titles
from manhwatok.config import Settings
from manhwatok.domain.models import SearchQuery

pytestmark = pytest.mark.skipif(
    os.environ.get("MANHWATOK_LIVE") != "1", reason="set MANHWATOK_LIVE=1 to hit real APIs"
)


def _keep_first_five(text: str) -> str:
    """Scripted 'editor': keep the title and the first five pick lines, comment out the rest."""
    out, kept = [], 0
    for line in text.splitlines():
        if line and not line.startswith(("#", "title:")):
            if kept >= 5:
                line = "# " + line
            kept += 1
        out.append(line)
    return "\n".join(out) + "\n"


def test_build_real_post(tmp_path):
    settings = Settings(data_dir=tmp_path)
    tools = build_post_tools(settings, _keep_first_five, print)
    query = SearchQuery(tags=["Time Manipulation", "Revenge"], limit=8)
    with build_store(settings) as store:
        chapters = build_chapter_source(settings, store.cache)
        built = build_post(
            lambda: suggest_titles(query, build_metadata(settings), chapters),
            "Manhwa where the MC *regresses* for *revenge*",
            None,
            "#manhwa #webtoon",
            "#43c9e4",
            tools,
            now=datetime.now(timezone.utc),
        )
    assert built is not None
    post, slides = built
    assert len(post.items) == 5
    assert len(slides) == 7
    for path in slides:
        with Image.open(path) as img:
            assert img.size == (1080, 1920)
    assert len(list(settings.covers_dir.iterdir())) == 5
    print(f"\nrendered post → {tools.posts.folder(post.id)}")
