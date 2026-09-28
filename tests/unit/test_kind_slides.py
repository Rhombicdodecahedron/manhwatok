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


def test_a_character_slide_shows_the_portrait_and_the_name(tmp_path, monkeypatch):
    from manhwatok.adapters import pillow_renderer
    from manhwatok.domain.models import CharacterPick

    names = []
    real = pillow_renderer.layout_item

    def spy(rank, name, pill, *a, **k):
        names.append((name, pill))
        return real(rank, name, pill, *a, **k)

    monkeypatch.setattr(pillow_renderer, "layout_item", spy)
    item = PostItem(manhwa=manhwa(anilist_id=1, title="T1"), character=CharacterPick(name="Jin"))
    portrait = cover_file(tmp_path / "ch", 1, color=(30, 210, 30), size=(230, 345))
    cover = cover_file(tmp_path / "c", 1, color=(220, 30, 30))
    p = post(items=[item], kind=PostKind.CHARACTERS)
    paths = PillowRenderer().render(p, {1: SlideArt(cover, None, portrait)}, tmp_path / "o")
    assert ("Jin", "T1") in names
    r, g, b = _px(paths[1], (540, 700))
    assert g > r + 80  # the portrait, not the cover


def test_characters_end_recaps_names_with_titles():
    from manhwatok.adapters.kind_slides import end_names
    from manhwatok.domain.models import CharacterPick

    item = PostItem(manhwa=manhwa(anilist_id=1, title="T1"), character=CharacterPick(name="Jin"))
    assert end_names(post(items=[item], kind=PostKind.CHARACTERS)) == ["Jin (T1)"]


def test_a_plain_slide_shows_the_cover_even_when_a_portrait_was_loaded(tmp_path):
    """The quad cover (and a guess post's clues) load portraits; a list slide in the plain
    style still shows the title's cover."""
    cover = cover_file(tmp_path / "c", 1, color=(220, 30, 30))
    portrait = cover_file(tmp_path / "ch", 1, color=(30, 210, 30), size=(230, 345))
    for kind in (PostKind.LIST, PostKind.GUESS):
        items = [PostItem(manhwa=manhwa(anilist_id=1, title="T1"))]
        paths = PillowRenderer().render(post(items=items, kind=kind), {1: SlideArt(cover, None, portrait)}, tmp_path / kind.value)
        reveal = paths[1] if kind is PostKind.LIST else paths[2]
        r, g, b = _px(reveal, (540, 600))
        assert r > g + 80, kind  # the red cover card, not the green portrait


def test_a_guess_posts_covers_do_not_show_the_answers(tmp_path):
    """Every cover version draws the clues, never the lettered covers (review finding 4)."""
    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in (1, 2, 3)]
    art = {
        i: SlideArt(
            cover_file(tmp_path / "c", i, color=(220, 30, 30)),
            None,
            gallery=(cover_file(tmp_path / f"s{i}", i, color=(30, 210, 30), size=(900, 1400)),),
        )
        for i in (1, 2, 3)
    }
    PillowRenderer().render(post(items=items, kind=PostKind.GUESS), art, tmp_path / "o")
    for style, xy in (("fan", (540, 560)), ("hero", (60, 300)), ("podium", (540, 520))):
        r, g, b = _px(tmp_path / "o" / f"cover-{style}.png", xy)
        assert not r > g + 60, style  # no red cover showing


def test_a_clue_cut_from_the_cover_keeps_clear_of_its_lettering():
    """Title logos sit at a cover's top or foot: a clue from the cover alone takes the middle
    (review finding 5)."""
    from manhwatok.adapters.kind_slides import clue_piece
    from manhwatok.adapters.pillow_renderer import _Art

    cover = Image.new("RGB", (460, 650), (30, 30, 220))
    _, (left, top, right, bottom) = clue_piece(_Art(cover, None, None, None), None)
    assert top >= 650 * 0.25 and bottom <= 650 * 0.75


def test_an_if_you_liked_cover_leads_with_the_seeds_art(tmp_path):
    """Review finding 7: the spec's seed-led hero, number and magazine covers."""
    seed = manhwa(anilist_id=99, title="Seed")
    items = [PostItem(manhwa=manhwa(anilist_id=1, title="T1"))]
    art = {
        1: SlideArt(cover_file(tmp_path / "c", 1, color=(220, 30, 30)), None),
        99: SlideArt(cover_file(tmp_path / "c", 99, color=(30, 30, 220)), None),
    }
    paths = PillowRenderer().render(post(items=items, kind=PostKind.SIMILAR, seed=seed), art, tmp_path / "o")
    r, g, b = _px(tmp_path / "o" / "cover-hero.png", (60, 300))
    assert b > r + 80
    assert len(paths) == 3  # the seed is no slide of its own


def test_a_character_slide_keeps_its_portrait_over_picked_art(tmp_path):
    from manhwatok.domain.models import CharacterPick

    item = PostItem(manhwa=manhwa(anilist_id=1, title="T1"), character=CharacterPick(name="Jin"))
    portrait = cover_file(tmp_path / "ch", 1, color=(30, 210, 30), size=(230, 345))
    picked = cover_file(tmp_path / "p", 1, color=(30, 30, 220), size=(600, 900))
    paths = PillowRenderer().render(post(items=[item], kind=PostKind.CHARACTERS), {1: SlideArt(None, None, portrait, picked)}, tmp_path / "o")
    r, g, b = _px(paths[1], (540, 700))
    assert g > b + 80  # the named character, not fan art
