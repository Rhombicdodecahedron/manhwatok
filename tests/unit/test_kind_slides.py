from PIL import Image

from manhwatok.adapters.pillow_renderer import PillowRenderer
from manhwatok.domain.models import PostKind
from manhwatok.domain.post import PostItem
from manhwatok.ports.posts import SlideArt
from tests.unit.fakes import cover_file, manhwa, post


def _px(path, xy):
    with Image.open(path) as img:
        return img.convert("RGB").getpixel(xy)


COLOURS = [(220, 30, 30), (30, 30, 230), (30, 210, 30), (230, 210, 30)]


def _versus(tmp_path, n=4):
    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in range(1, n + 1)]
    art = {
        i: SlideArt(cover_file(tmp_path / "c", i, color=COLOURS[i - 1]), None)
        for i in range(1, n + 1)
    }
    return post(items=items, kind=PostKind.VERSUS), art


def test_versus_draws_one_slide_per_pair_top_against_bottom(tmp_path):
    p, art = _versus(tmp_path)
    paths = PillowRenderer().render(p, art, tmp_path / "out")
    assert len(paths) == 4  # cover, 2 rounds, end
    r, g, b = _px(paths[1], (60, 200))
    assert r > b + 80  # T1 on top
    r, g, b = _px(paths[1], (60, 1100))
    assert b > r + 80  # T2 below
    r, g, b = _px(paths[2], (60, 200))
    assert g > r + 80  # round 2: T3 on top


def test_versus_has_a_vs_badge_in_the_accent(tmp_path):
    from manhwatok.domain.color import hex_to_rgb, readable_accent

    p, art = _versus(tmp_path)
    paths = PillowRenderer().render(p, art, tmp_path / "out")
    accent = hex_to_rgb(readable_accent(p.accent))
    assert all(abs(a - b) < 40 for a, b in zip(_px(paths[1], (470, 960)), accent))


def test_versus_end_recaps_the_rounds():
    from manhwatok.adapters.kind_slides import end_names

    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in (1, 2, 3, 4)]
    assert end_names(post(items=items, kind=PostKind.VERSUS)) == ["T1 vs T2", "T3 vs T4"]


def test_a_list_posts_end_names_are_its_titles():
    from manhwatok.adapters.kind_slides import end_names

    assert end_names(post()) == ["Title 1", "Title 2", "Title 3"]


def test_a_versus_post_asks_which_wins_by_default():
    from datetime import datetime, timezone

    from manhwatok.app.build_post import create_post

    items = [PostItem(manhwa=manhwa(anilist_id=i)) for i in (1, 2)]
    p = create_post("x", datetime.now(timezone.utc), [], "T", items, None, None, None, kind=PostKind.VERSUS)
    assert p.cta_title == "Which one *wins?*"
