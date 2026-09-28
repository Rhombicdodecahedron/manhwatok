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


def test_guess_puts_a_clue_before_each_reveal(tmp_path):
    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in (1, 2)]
    p = post(items=items, kind=PostKind.GUESS)
    paths = PillowRenderer().render(p, {1: SlideArt(None, None), 2: SlideArt(None, None)}, tmp_path / "o")
    assert len(paths) == 6  # cover, clue, reveal, clue, reveal, end


def test_the_clue_prefers_picked_art_over_the_lettered_cover():
    from manhwatok.adapters.kind_slides import clue_piece
    from manhwatok.adapters.pillow_renderer import _Art

    cover = Image.new("RGB", (460, 650), (200, 30, 30))
    pick = Image.new("RGB", (600, 900), (30, 30, 200))
    img, box = clue_piece(_Art(cover, None, None, pick), None)
    assert img is pick
    assert box[2] - box[0] < 600 * 0.7  # zoomed in, not the whole picture


def test_the_clue_falls_back_to_the_cover():
    from manhwatok.adapters.kind_slides import clue_piece
    from manhwatok.adapters.pillow_renderer import _Art

    cover = Image.new("RGB", (460, 650), (200, 30, 30))
    img, _ = clue_piece(_Art(cover, None, None, None), None)
    assert img is cover


def test_the_clue_slide_shows_the_guess_number_in_the_accent(tmp_path):
    from manhwatok.adapters.layout import layout_guess
    from manhwatok.domain.color import hex_to_rgb, readable_accent

    items = [PostItem(manhwa=manhwa(anilist_id=1, title="T1"))]
    p = post(items=items, kind=PostKind.GUESS)
    paths = PillowRenderer().render(p, {1: SlideArt(None, None)}, tmp_path / "o")
    big = layout_guess(1, "").number.box
    accent = hex_to_rgb(readable_accent(p.accent))
    with Image.open(paths[1]) as img:
        row = [img.convert("RGB").getpixel((x, big.y + big.h // 2)) for x in range(big.x, big.right)]
    assert any(all(abs(a - b) < 30 for a, b in zip(px, accent)) for px in row)


def test_guess_hint():
    from manhwatok.domain.labels import guess_hint
    from manhwatok.domain.models import Status

    m = manhwa(genres=["Action", "Fantasy", "Drama"], start_year=2018, status=Status.FINISHED)
    assert guess_hint(m) == "Action · Fantasy · 2018 · completed"
    assert guess_hint(manhwa(genres=[], status=Status.UNKNOWN)) == ""


def test_a_later_titles_clue_uses_its_scene_not_its_cover(tmp_path):
    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in (1, 2)]
    scene = cover_file(tmp_path / "s", 2, color=(30, 210, 30), size=(900, 1400))
    art = {
        1: SlideArt(None, None),
        2: SlideArt(cover_file(tmp_path / "c", 2, color=(220, 30, 30)), None, gallery=(scene,)),
    }
    paths = PillowRenderer().render(post(items=items, kind=PostKind.GUESS), art, tmp_path / "o")
    r, g, b = _px(paths[3], (540, 300))  # the second title's clue
    assert g > r + 80
