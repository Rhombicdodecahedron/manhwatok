import pytest
from PIL import Image

from manhwatok.adapters.pillow_renderer import PillowRenderer
from manhwatok.domain.color import hex_to_rgb, readable_accent
from manhwatok.domain.errors import StorageError
from manhwatok.domain.models import ArtStyle, CoverStyle
from manhwatok.domain.post import PostItem
from manhwatok.ports.posts import SlideArt
from tests.unit.fakes import cover_file, manhwa, post


def _art(covers, banners=None):
    """The renderer takes a cover+banner pair per item; most tests only care about covers."""
    banners = banners or {}
    return {i: SlideArt(cover, banners.get(i)) for i, cover in covers.items()}


def _post(n=3):
    items = [
        PostItem(
            manhwa=manhwa(anilist_id=i, title=f"Title {i}", cover_color="#6b1a1a"),
            hook=f"Hook {i}.",
        )
        for i in range(1, n + 1)
    ]
    return post(items=items)


def test_renders_cover_items_and_end_slide_at_tiktok_size(tmp_path):
    p = _post(3)
    covers = {i: cover_file(tmp_path / "covers", i) for i in (1, 2, 3)}
    paths = PillowRenderer().render(p, _art(covers), tmp_path / "out")
    assert [x.name for x in paths] == ["01.png", "02.png", "03.png", "04.png", "05.png"]
    for x in paths:
        with Image.open(x) as img:
            assert img.size == (1080, 1920)
            assert img.mode == "RGB"


def test_rerender_removes_stale_slides(tmp_path):
    out = tmp_path / "out"
    covers = {i: cover_file(tmp_path / "covers", i) for i in (1, 2, 3)}
    PillowRenderer().render(_post(3), _art(covers), out)
    PillowRenderer().render(_post(1), _art(covers), out)
    assert sorted(x.name for x in out.glob("[0-9][0-9].png")) == ["01.png", "02.png", "03.png"]


def test_missing_or_broken_cover_still_renders(tmp_path):
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    paths = PillowRenderer().render(_post(2), _art({1: None, 2: broken}), tmp_path / "out")
    assert len(paths) == 4


def test_single_item_post(tmp_path):
    paths = PillowRenderer().render(_post(1), _art({1: cover_file(tmp_path, 1)}), tmp_path / "out")
    assert len(paths) == 3


def test_manhwa_slide_uses_readable_accent_for_rank(tmp_path):
    """#6b1a1a is too dark; the rank number must be drawn in a lightened red, not the raw colour."""
    PillowRenderer().render(
        _post(1), _art({1: cover_file(tmp_path, 1, color=(20, 20, 20))}), tmp_path / "out"
    )
    with Image.open(tmp_path / "out" / "02.png") as img:
        colors = {c for _, c in img.getcolors(maxcolors=1 << 20)}
    assert (0x6B, 0x1A, 0x1A) not in colors
    assert hex_to_rgb(readable_accent("#6b1a1a")) in colors


def test_inactive_progress_segments_are_dimmed_not_white(tmp_path):
    from manhwatok.adapters.layout import layout_cover

    p = _post(3)
    covers = {i: cover_file(tmp_path / "covers", i, color=(0, 0, 0)) for i in (1, 2, 3)}
    PillowRenderer().render(p, _art(covers), tmp_path / "out")
    seg = layout_cover(p.title, 3).bar[1]
    with Image.open(tmp_path / "out" / "01.png") as img:
        r, g, b = img.getpixel((seg.x + seg.w // 2, seg.y + seg.h // 2))
    assert (r, g, b) != (255, 255, 255)
    assert 40 < r < 200 and r == g == b  # ~30% white over a near-black background


def test_cover_slide_missing_cover_survives_a_bad_accent(tmp_path):
    """A hand-edited post.json can have a non-hex accent; the missing-cover fallback must not
    ValueError — it should fall back like readable_accent does everywhere else."""
    p = _post(1).model_copy(update={"accent": "not-a-color"})
    paths = PillowRenderer().render(p, _art({1: None}), tmp_path / "out")
    assert len(paths) == 3


def test_out_dir_blocked_by_a_file_raises_storage_error(tmp_path):
    blocker = tmp_path / "out"
    blocker.write_bytes(b"not a directory")
    with pytest.raises(StorageError):
        PillowRenderer().render(_post(1), _art({1: None}), blocker)


def test_slide_save_failure_raises_storage_error(tmp_path, monkeypatch):
    def boom(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Image.Image, "save", boom)
    with pytest.raises(StorageError):
        PillowRenderer().render(_post(1), _art({1: None}), tmp_path / "out")


def test_end_slide_uses_accent_gradient_when_no_covers(tmp_path):
    PillowRenderer().render(_post(2), _art({1: None, 2: None}), tmp_path / "out")
    with Image.open(tmp_path / "out" / "04.png") as img:
        top = img.getpixel((20, 20))
    assert top != (0, 0, 0)
    assert top[2] > top[0]  # default accent #43c9e4 is blue-dominant


def test_end_slide_grid_is_blurred_as_one_image_without_seams(tmp_path):
    colors = [(230, 40, 40), (40, 40, 230), (40, 230, 40), (230, 230, 40)]
    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in range(1, 5)]
    covers = {i: cover_file(tmp_path / "c", i, color=colors[i - 1]) for i in range(1, 5)}
    PillowRenderer().render(post(items=items), _art(covers), tmp_path / "out")
    with Image.open(tmp_path / "out" / "06.png") as img:
        across_x = [img.getpixel((x, 300)) for x in (538, 539, 540, 541)]  # above the title
        across_y = [img.getpixel((50, y)) for y in (958, 959, 960, 961)]  # left of the list

    def biggest_step(pixels):
        return max(abs(a - b) for p, q in zip(pixels, pixels[1:]) for a, b in zip(p, q))

    assert biggest_step(across_x) <= 6
    assert biggest_step(across_y) <= 6


def test_end_slide_uses_the_posts_cta_texts(tmp_path, monkeypatch):
    from manhwatok.adapters import pillow_renderer

    seen = []
    real = pillow_renderer.layout_end

    def spy(names, cta_title, cta_follow, byline=""):
        seen.append((names, cta_title, cta_follow))
        return real(names, cta_title, cta_follow, byline)

    monkeypatch.setattr(pillow_renderer, "layout_end", spy)
    p = _post(1).model_copy(update={"cta_title": "Seen *these*?", "cta_follow": "More tomorrow"})
    PillowRenderer().render(p, _art({1: None}), tmp_path / "out")
    assert seen == [(["Title 1"], "Seen *these*?", "More tomorrow")]


# --- background art (Phase 5) ---------------------------------------------------------------


def _red_cover(tmp_path):
    return cover_file(tmp_path / "c", 1, color=(230, 30, 30))


def _blue_banner(tmp_path):
    return cover_file(tmp_path / "b", 1, color=(30, 30, 230), size=(1900, 400))


def _background_post():
    return _post(1).model_copy(update={"art": ArtStyle.BACKGROUND})


def _corner(out_dir, xy=(20, 20)):
    with Image.open(out_dir / "02.png") as img:
        return img.getpixel(xy)


def test_background_art_paints_the_banner_behind_the_card(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), _blue_banner(tmp_path))}
    PillowRenderer().render(_background_post(), art, tmp_path / "out")
    r, g, b = _corner(tmp_path / "out")
    assert b > r  # the blue banner, not the red cover


def test_background_art_falls_back_to_the_cover_when_there_is_no_banner(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), None)}
    PillowRenderer().render(_background_post(), art, tmp_path / "out")
    r, g, b = _corner(tmp_path / "out")
    assert r > b  # about half of manhwa have no banner — they look like they always did


def test_art_none_ignores_a_banner_that_is_already_on_disk(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), _blue_banner(tmp_path))}
    PillowRenderer().render(_post(1), art, tmp_path / "out")
    r, g, b = _corner(tmp_path / "out")
    assert r > b


def test_banner_is_cropped_to_fill_the_slide_not_letterboxed(tmp_path):
    """A banner is ~4.75:1 against a 0.56:1 slide — resizing it to fit would leave bars.
    Sampled down both edges, clear of the card and of the bottom gradient under the text."""
    art = {1: SlideArt(_red_cover(tmp_path), _blue_banner(tmp_path))}
    PillowRenderer().render(_background_post(), art, tmp_path / "out")
    with Image.open(tmp_path / "out" / "02.png") as img:
        edges = [img.getpixel((x, y)) for x in (20, 1059) for y in (20, 500, 900)]
    for r, g, b in edges:
        assert b > r


def test_background_art_still_renders_when_the_banner_file_is_broken(tmp_path):
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    art = {1: SlideArt(_red_cover(tmp_path), broken)}
    paths = PillowRenderer().render(_background_post(), art, tmp_path / "out")
    assert len(paths) == 3
    r, g, b = _corner(tmp_path / "out")
    assert r > b  # falls back to the cover


# --- panel art (Phase 5) ---------------------------------------------------------------------


def _panel_post():
    return _post(1).model_copy(update={"art": ArtStyle.PANEL})


def _panel_box():
    from manhwatok.adapters.layout import layout_item

    return layout_item(1, "TITLE 1", "ongoing", "Hook 1.", art=ArtStyle.PANEL).cover_area


def test_panel_art_fills_the_wide_box_with_the_banner(tmp_path):
    """A 4.75:1 banner in a 2.1:1 box: fitting it would leave the box's own top and bottom
    showing the backdrop instead of art."""
    art = {1: SlideArt(_red_cover(tmp_path), _blue_banner(tmp_path))}
    PillowRenderer().render(_panel_post(), art, tmp_path / "out")
    box = _panel_box()
    mid_x = box.x + box.w // 2
    with Image.open(tmp_path / "out" / "02.png") as img:
        inside = [img.getpixel((mid_x, y)) for y in (box.y + 6, box.y + box.h // 2, box.bottom - 6)]
    for r, g, b in inside:
        assert b > r + 40  # solid banner blue top to bottom of the box


def test_panel_art_crops_the_cover_into_the_same_box_without_a_banner(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), None)}
    PillowRenderer().render(_panel_post(), art, tmp_path / "out")
    box = _panel_box()
    mid_x = box.x + box.w // 2
    with Image.open(tmp_path / "out" / "02.png") as img:
        inside = [img.getpixel((mid_x, y)) for y in (box.y + 6, box.y + box.h // 2, box.bottom - 6)]
    for r, g, b in inside:
        assert r > b + 40  # the cover, cropped — same shape as a banner slide


def test_panel_art_renders_with_no_images_at_all(tmp_path):
    paths = PillowRenderer().render(_panel_post(), {1: SlideArt(None, None)}, tmp_path / "out")
    assert len(paths) == 3


def test_panel_art_still_uses_the_banner_as_the_backdrop(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), _blue_banner(tmp_path))}
    PillowRenderer().render(_panel_post(), art, tmp_path / "out")
    r, g, b = _corner(tmp_path / "out")  # outside the panel box
    assert b > r


def _banded_cover(tmp_path):
    """A cover whose face-height band (top 30%) is green and the rest black, so where the
    panel crop takes its band from is visible in the output."""
    img = Image.new("RGB", (460, 650), (0, 0, 0))
    for y in range(195):
        for x in range(460):
            img.putpixel((x, y), (0, 220, 0))
    folder = tmp_path / "banded"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "1.jpg"
    img.save(path)
    return path


def test_panel_crops_a_cover_from_where_the_face_usually_is(tmp_path):
    """Centre-cropping a 0.7:1 cover to 2.1:1 lands on the torso; the crop sits higher so it
    catches the character instead."""
    art = {1: SlideArt(_banded_cover(tmp_path), None)}
    PillowRenderer().render(_panel_post(), art, tmp_path / "out")
    box = _panel_box()
    with Image.open(tmp_path / "out" / "02.png") as img:
        top_band = img.getpixel((box.x + box.w // 2, box.y + 6))
    r, g, b = top_band
    assert g > r + 80 and g > b + 80  # the green band, not the black below it


# --- character art (Phase 5) -----------------------------------------------------------------


def _green_character(tmp_path):
    """AniList character images are small portraits, ~230x345."""
    return cover_file(tmp_path / "ch", 1, color=(30, 210, 30), size=(230, 345))


def _character_post():
    return _post(1).model_copy(update={"art": ArtStyle.CHARACTER})


def _card_pixel(out_dir, xy=(540, 500)):
    with Image.open(out_dir / "02.png") as img:
        return img.getpixel(xy)


def test_character_art_puts_the_portrait_where_the_cover_was(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), None, _green_character(tmp_path))}
    PillowRenderer().render(_character_post(), art, tmp_path / "out")
    r, g, b = _card_pixel(tmp_path / "out")
    assert g > r + 40 and g > b + 40  # the character, not the red cover


def test_character_art_keeps_the_cover_as_the_backdrop(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), None, _green_character(tmp_path))}
    PillowRenderer().render(_character_post(), art, tmp_path / "out")
    r, g, b = _corner(tmp_path / "out")  # outside the card
    assert r > g  # the blurred cover, as always


def test_character_art_falls_back_to_the_cover_when_there_is_no_portrait(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), None, None)}
    PillowRenderer().render(_character_post(), art, tmp_path / "out")
    r, g, b = _card_pixel(tmp_path / "out")
    assert r > g + 40  # the cover card, exactly as the plain style draws it


def test_character_art_renders_with_no_images_at_all(tmp_path):
    paths = PillowRenderer().render(_character_post(), {1: SlideArt(None, None, None)}, tmp_path / "out")
    assert len(paths) == 3


def _character_box():
    from manhwatok.adapters.layout import layout_item

    return layout_item(1, "TITLE 1", "ongoing", "Hook 1.", art=ArtStyle.CHARACTER).cover_area


def _banded_portrait(tmp_path):
    """A portrait with a distinct band at each end, so a vertical crop is visible in output."""
    img = Image.new("RGB", (230, 345), (30, 210, 30))
    for y in range(20):
        for x in range(230):
            img.putpixel((x, y), (230, 0, 230))          # magenta cap
            img.putpixel((x, 344 - y), (0, 220, 220))    # cyan foot
    folder = tmp_path / "band"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "1.png"
    img.save(path)
    return path


def _column(out_dir, box, x=540):
    """Down the middle of the drawn image. Channels are compared to each other, not to fixed
    values, because the bottom gradient darkens everything near the text."""
    with Image.open(out_dir / "02.png") as img:
        return [img.getpixel((x, y)) for y in range(box.y, box.bottom)]


def test_character_art_shows_the_whole_portrait_uncropped(tmp_path):
    """Filling the box would crop a 0.67:1 portrait top and bottom; both ends must survive."""
    art = {1: SlideArt(_red_cover(tmp_path), None, _banded_portrait(tmp_path))}
    PillowRenderer().render(_character_post(), art, tmp_path / "out")
    column = _column(tmp_path / "out", _character_box())
    assert any(r > g + 40 and b > g + 40 for r, g, b in column), "magenta cap was cropped"
    assert any(g > r + 40 and b > r + 40 for r, g, b in column), "cyan foot was cropped"


def test_character_art_is_drawn_wider_than_the_old_cover_card(tmp_path):
    """Bigger than the 620-wide cover card, even though it is not cropped to fill."""
    from manhwatok.adapters.layout import COVER_MAX_W

    art = {1: SlideArt(_red_cover(tmp_path), None, _green_character(tmp_path))}
    PillowRenderer().render(_character_post(), art, tmp_path / "out")
    box = _character_box()
    with Image.open(tmp_path / "out" / "02.png") as img:
        row = [img.getpixel((x, box.y + box.h // 2)) for x in range(box.x, box.right)]
    drawn = sum(1 for r, g, b in row if g > r + 40 and g > b + 40)
    assert drawn > COVER_MAX_W


def test_character_art_is_drawn_bigger_than_the_plain_cover_card(tmp_path):
    """The point of the style: the portrait is the slide's subject, not a card on it."""
    char = _character_box()
    from manhwatok.adapters.layout import layout_item

    plain = layout_item(1, "TITLE 1", "ongoing", "Hook 1.").cover_area
    assert char.w * char.h > plain.w * plain.h


# --- hand-picked art -------------------------------------------------------------------------


def _blue_pick(tmp_path):
    return cover_file(tmp_path / "pick", 1, color=(30, 30, 230), size=(500, 700))


def test_hand_picked_art_beats_the_cover(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), None, None, _blue_pick(tmp_path))}
    PillowRenderer().render(_post(1), art, tmp_path / "out")
    r, g, b = _card_pixel(tmp_path / "out")
    assert b > r + 40


def test_hand_picked_art_beats_the_character_portrait(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), None, _green_character(tmp_path), _blue_pick(tmp_path))}
    PillowRenderer().render(_character_post(), art, tmp_path / "out")
    r, g, b = _card_pixel(tmp_path / "out")
    assert b > g + 40


def test_hand_picked_art_beats_the_banner_in_the_panel(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), _blue_banner(tmp_path), None, _green_character(tmp_path))}
    PillowRenderer().render(_panel_post(), art, tmp_path / "out")
    box = _panel_box()
    with Image.open(tmp_path / "out" / "02.png") as img:
        r, g, b = img.getpixel((box.x + box.w // 2, box.y + box.h // 2))
    assert g > b + 40  # the pick, not the blue banner


def test_hand_picked_art_leaves_the_backdrop_to_the_style(tmp_path):
    """The pick replaces the slide's subject, not the blur behind it."""
    art = {1: SlideArt(_red_cover(tmp_path), None, None, _blue_pick(tmp_path))}
    PillowRenderer().render(_post(1), art, tmp_path / "out")
    r, g, b = _corner(tmp_path / "out")
    assert r > b  # still the blurred red cover


# --- scene art -------------------------------------------------------------------------------


def _scene_post():
    return _post(1).model_copy(update={"art": ArtStyle.SCENE})


def _wide_pick(tmp_path):
    return cover_file(tmp_path / "pick", 1, color=(30, 30, 230), size=(1600, 900))


def _white_pick(tmp_path):
    return cover_file(tmp_path / "pick", 1, color=(255, 255, 255), size=(1080, 1920))


LONG_TITLE = "The Reincarnated Assassin Who Became the Strongest Swordmaster"
LONG_HOOK = "He wakes up again " * 25


def _wordy_scene_post():
    """The worst case for legibility: a 2-line title and a 3-line hook push the rank number
    highest up the slide, onto the brightest part of the picture."""
    item = PostItem(
        manhwa=manhwa(anilist_id=1, title=LONG_TITLE, cover_color="#6b1a1a"), hook=LONG_HOOK
    )
    return post(items=[item]).model_copy(update={"art": ArtStyle.SCENE})


def _wordy_rank_y():
    from manhwatok.adapters.layout import layout_item

    label = "ongoing"
    return layout_item(1, LONG_TITLE, label, LONG_HOOK, art=ArtStyle.SCENE).rank.box.y


def test_scene_art_fills_the_slide_edge_to_edge_instead_of_letterboxing(tmp_path):
    """A 1600x900 pick fitted into the slide would leave the red backdrop showing at the edges.
    Probes stay above y=1000: below that the scrim crushes both channels."""
    art = {1: SlideArt(_red_cover(tmp_path), None, None, _wide_pick(tmp_path))}
    PillowRenderer().render(_scene_post(), art, tmp_path / "out")
    with Image.open(tmp_path / "out" / "02.png") as img:
        edges = [img.getpixel(xy) for xy in ((4, 4), (540, 4), (1075, 4), (4, 1000), (1075, 1000))]
    for r, g, b in edges:
        assert b > r + 40


def test_scene_art_has_square_corners(tmp_path):
    """No card means no 24px rounding — the rounded corner would show the backdrop through it."""
    art = {1: SlideArt(_red_cover(tmp_path), None, None, _wide_pick(tmp_path))}
    PillowRenderer().render(_scene_post(), art, tmp_path / "out")
    with Image.open(tmp_path / "out" / "02.png") as img:
        corners = [img.getpixel((0, 0)), img.getpixel((1079, 0))]
    for r, g, b in corners:
        assert b > r


def test_scene_art_uses_the_hand_picked_pin_over_the_cover(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), None, None, _wide_pick(tmp_path))}
    PillowRenderer().render(_scene_post(), art, tmp_path / "out")
    with Image.open(tmp_path / "out" / "02.png") as img:
        r, g, b = img.getpixel((540, 300))
    assert b > r + 40


def test_scene_art_keeps_the_text_readable_over_a_bright_picture(tmp_path):
    """x=960 is clear of the left-aligned text, so these are backdrop pixels, not glyphs: the
    picture must be dark under the topmost line and still bright well above it."""
    art = {1: SlideArt(_red_cover(tmp_path), None, None, _white_pick(tmp_path))}
    PillowRenderer().render(_wordy_scene_post(), art, tmp_path / "out")
    with Image.open(tmp_path / "out" / "02.png") as img:
        under_text = img.getpixel((960, _wordy_rank_y()))
        up_top = img.getpixel((960, 200))
        colors = {c for _, c in img.getcolors(maxcolors=1 << 20)}
    assert all(channel < 90 for channel in under_text)
    assert all(channel > 200 for channel in up_top)
    assert hex_to_rgb(readable_accent("#6b1a1a")) in colors


def test_scene_art_starts_its_scrim_higher_up_than_the_other_styles(tmp_path):
    """The shared scrim only reaches y=1000, which leaves the topmost text on bare picture here.
    Pin where the darkening begins rather than its exact height: y=900 must already be dimmed,
    y=300 must not be touched at all."""
    art = {1: SlideArt(_red_cover(tmp_path), None, None, _white_pick(tmp_path))}
    PillowRenderer().render(_scene_post(), art, tmp_path / "out")
    with Image.open(tmp_path / "out" / "02.png") as img:
        assert all(channel < 200 for channel in img.getpixel((960, 900)))
        assert all(channel > 250 for channel in img.getpixel((960, 300)))


def test_scene_art_falls_back_to_the_cover_filling_the_slide(tmp_path):
    """Sharp and full-brightness, unlike the `none` style's cover blurred to 0.42."""
    art = {1: SlideArt(_red_cover(tmp_path), None, None, None)}
    PillowRenderer().render(_scene_post(), art, tmp_path / "out")
    with Image.open(tmp_path / "out" / "02.png") as img:
        r, g, b = img.getpixel((4, 300))
    assert r > 180 and r > b + 100


def test_scene_art_ignores_a_banner_that_is_already_on_disk(tmp_path):
    art = {1: SlideArt(_red_cover(tmp_path), _blue_banner(tmp_path))}
    PillowRenderer().render(_scene_post(), art, tmp_path / "out")
    with Image.open(tmp_path / "out" / "02.png") as img:
        r, g, b = img.getpixel((4, 300))
    assert r > b


def test_scene_art_renders_with_no_images_at_all(tmp_path):
    paths = PillowRenderer().render(_scene_post(), {1: SlideArt(None, None)}, tmp_path / "out")
    assert len(paths) == 3
    r, g, b = _corner(tmp_path / "out")
    assert (r, g, b) != (0, 0, 0)


# --- cover versions ----------------------------------------------------------------------------


def _pixel(path, xy):
    with Image.open(path) as img:
        return img.getpixel(xy)


def _same_image(a, b):
    with Image.open(a) as x, Image.open(b) as y:
        return x.tobytes() == y.tobytes()


def test_render_writes_every_cover_version_next_to_the_slides(tmp_path):
    covers = {i: cover_file(tmp_path / "covers", i) for i in (1, 2, 3)}
    paths = PillowRenderer().render(_post(3), _art(covers), tmp_path / "out")
    out = tmp_path / "out"
    assert len(paths) == 5  # the versions are extras, never slides
    for style in CoverStyle:
        with Image.open(out / f"cover-{style.value}.png") as img:
            assert img.size == (1080, 1920)
    assert _same_image(out / "01.png", out / "cover-fan.png")


@pytest.mark.parametrize("style", list(CoverStyle))
def test_the_posts_cover_version_becomes_the_first_slide(tmp_path, style):
    covers = {i: cover_file(tmp_path / "covers", i) for i in (1, 2, 3)}
    p = _post(3).model_copy(update={"cover": style})
    PillowRenderer().render(p, _art(covers), tmp_path / "out")
    out = tmp_path / "out"
    assert _same_image(out / "01.png", out / f"cover-{style.value}.png")


def test_rerender_removes_stale_cover_versions(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "cover-old.png").write_bytes(b"png")
    PillowRenderer().render(_post(1), _art({1: None}), out)
    assert sorted(x.name for x in out.glob("cover-*.png")) == [
        f"cover-{s.value}.png" for s in sorted(CoverStyle, key=lambda s: s.value)
    ]


QUADRANTS = [(270, 300), (810, 300), (270, 1020), (810, 1020)]  # the lower two under the scrim
COLORS = [(230, 30, 30), (30, 210, 30), (30, 30, 230), (230, 210, 30)]


def _dominant(rgb):
    return max(range(3), key=lambda c: rgb[c]) if max(rgb) - min(rgb) > 60 else None


def test_quad_cover_puts_one_character_in_each_quadrant(tmp_path):
    art = {
        i: SlideArt(
            cover_file(tmp_path / "c", i, color=(128, 128, 128)),
            None,
            cover_file(tmp_path / "ch", i, color=COLORS[i - 1], size=(230, 345)),
        )
        for i in (1, 2, 3, 4)
    }
    PillowRenderer().render(_post(4), art, tmp_path / "out")
    for xy, color in zip(QUADRANTS, COLORS):
        px = _pixel(tmp_path / "out" / "cover-quad.png", xy)
        for i in range(3):
            for j in range(3):
                if color[i] > color[j] + 100:  # same hue, whatever the scrim took off
                    assert px[i] > px[j] + 30, (xy, px, color)


def test_quad_cover_falls_back_to_picked_art_then_the_cover(tmp_path):
    art = {
        1: SlideArt(_red_cover(tmp_path), None, None, None),
        2: SlideArt(
            cover_file(tmp_path / "c", 2, color=(128, 128, 128)),
            None,
            None,
            cover_file(tmp_path / "pick", 2, color=(30, 30, 230)),
        ),
    }
    PillowRenderer().render(_post(2), art, tmp_path / "out")
    quad = tmp_path / "out" / "cover-quad.png"
    assert _dominant(_pixel(quad, QUADRANTS[0])) == 0  # red cover
    assert _dominant(_pixel(quad, QUADRANTS[1])) == 2  # blue pick beats grey cover
    assert _dominant(_pixel(quad, QUADRANTS[2])) == 0  # two picks repeat to fill four


def test_quad_cover_renders_with_no_images_at_all(tmp_path):
    PillowRenderer().render(_post(1), {1: SlideArt(None, None)}, tmp_path / "out")
    assert _pixel(tmp_path / "out" / "cover-quad.png", (20, 20)) != (0, 0, 0)


def test_hero_cover_fills_the_slide_with_the_first_picks_art(tmp_path):
    art = {
        1: SlideArt(_red_cover(tmp_path), None, None, cover_file(tmp_path / "pick", 1, color=(30, 30, 230))),
        2: SlideArt(cover_file(tmp_path / "c", 2, color=(30, 210, 30)), None),
    }
    PillowRenderer().render(_post(2), art, tmp_path / "out")
    r, g, b = _pixel(tmp_path / "out" / "cover-hero.png", (4, 300))
    assert b > 180 and b > r + 100  # sharp, full brightness, the pick over the cover


def test_hero_cover_uses_the_cover_without_picked_art(tmp_path):
    PillowRenderer().render(_post(1), {1: SlideArt(_red_cover(tmp_path), None)}, tmp_path / "out")
    r, g, b = _pixel(tmp_path / "out" / "cover-hero.png", (4, 300))
    assert r > 180 and r > b + 100


def _byline_row(path):
    """Pixels across the byline line, centred at the foot of the slide."""
    from manhwatok.adapters.layout import byline_of

    placed = byline_of("by @reads")
    box, start = placed.box, placed.line_x(0)
    with Image.open(path) as img:
        return [img.getpixel((x, box.y + box.h // 2)) for x in range(start, start + 150)]


def _signed(tmp_path, art=ArtStyle.NONE, account="reads"):
    covers = {i: cover_file(tmp_path / "covers", i) for i in (1, 2, 3)}
    p = _post(3).model_copy(update={"art": art, "account": account})
    return PillowRenderer().render(p, _art(covers), tmp_path / f"{art.value}-{account}")


@pytest.mark.parametrize("art", list(ArtStyle))
def test_every_slide_of_an_accounts_post_is_signed(tmp_path, art):
    for path in _signed(tmp_path, art):
        assert any(min(px) > 170 for px in _byline_row(path)), path.name


def test_a_post_without_an_account_is_not_signed(tmp_path):
    for path in _signed(tmp_path, account=None):
        assert not any(min(px) > 170 for px in _byline_row(path)), path.name


def test_the_byline_reads_on_bright_art(tmp_path):
    """A shadow under it, so it never disappears into a white panel."""
    white = cover_file(tmp_path / "w", 1, color=(255, 255, 255))
    p = _post(1).model_copy(update={"art": ArtStyle.SCENE, "account": "reads"})
    out = PillowRenderer().render(p, {1: SlideArt(white, None)}, tmp_path / "out")
    row = _byline_row(out[1])
    assert any(max(px) < 150 for px in row)  # the shadow


def test_the_bylines_shadow_sits_under_its_own_text(tmp_path, monkeypatch):
    """The shadow follows the byline's alignment: a centred byline with a left-aligned shadow
    printed a second, darker copy of the handle further left."""
    from manhwatok.adapters import pillow_renderer

    placements = []
    real = pillow_renderer._draw_text

    def spy(draw, placed, color, accent):
        if placed.text.line_text(0) == "@reads":
            placements.append(placed.line_x(0))
        return real(draw, placed, color, accent)

    monkeypatch.setattr(pillow_renderer, "_draw_text", spy)
    p = _post(1).model_copy(update={"account": "reads"})
    PillowRenderer().render(p, _art({1: None}), tmp_path / "out")
    assert placements, "the byline was never drawn"
    # Every slide draws it twice: the shadow first, two pixels off its own text, never elsewhere.
    assert {shadow - text for shadow, text in zip(placements[::2], placements[1::2])} == {2}


# --- chapter posts ------------------------------------------------------------------------------


def _panels(tmp_path, colours):
    from PIL import Image

    folder = tmp_path / "post"
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for n, colour in enumerate(colours, 1):
        name = f"panel-{n:03d}.png"
        Image.new("RGB", (1080, 1920), colour).save(folder / name)
        names.append(name)
    return folder, names


def _chapter_post(tmp_path, colours=((200, 40, 40), (40, 200, 40)), **fields):
    from tests.unit.fakes import chapter_part, chapter_post

    folder, names = _panels(tmp_path, colours)
    part = chapter_part(panels=names, to_panel=len(names), **fields)
    return chapter_post(chapter=part), folder


def test_a_chapter_post_renders_a_cover_its_panels_and_an_end_slide_at_tiktok_size(tmp_path):
    post, folder = _chapter_post(tmp_path)
    paths = PillowRenderer().render(post, {}, folder)
    assert [p.name for p in paths] == ["01.png", "02.png", "03.png", "04.png"]
    for path in paths:
        with Image.open(path) as img:
            assert img.size == (1080, 1920) and img.mode == "RGB"


def test_a_panel_slide_is_the_panel_itself(tmp_path):
    post, folder = _chapter_post(tmp_path)
    paths = PillowRenderer().render(post, {}, folder)
    assert _dominant(_pixel(paths[1], (540, 500))) == 0  # the red panel, untouched
    assert _dominant(_pixel(paths[2], (540, 500))) == 1  # then the green one


def test_a_chapter_post_signs_every_slide(tmp_path):
    post, folder = _chapter_post(tmp_path)
    signed = post.model_copy(update={"account": "reads"})
    for path in PillowRenderer().render(signed, {}, folder):
        assert any(min(px) > 170 for px in _byline_row(path)), path.name


def test_a_panel_that_is_not_slide_sized_is_fitted_onto_the_slide(tmp_path):
    post, folder = _chapter_post(tmp_path)
    Image.new("RGB", (400, 400), (40, 40, 200)).save(folder / post.chapter.panels[0])
    paths = PillowRenderer().render(post, {}, folder)
    with Image.open(paths[1]) as img:
        assert img.size == (1080, 1920)
    assert _dominant(_pixel(paths[1], (540, 960))) == 2


def test_the_chapter_cover_skips_a_black_opening_panel_for_a_drawn_one(tmp_path):
    """Chapters often open on a black page; blurring it gives a cover with nothing on it."""
    post, folder = _chapter_post(tmp_path, colours=((2, 2, 2), (40, 200, 40)))
    paths = PillowRenderer().render(post, {}, folder)
    assert _dominant(_pixel(paths[0], (540, 200))) == 1  # the drawn panel, blurred


def test_the_chapter_cover_uses_the_only_panel_there_is(tmp_path):
    post, folder = _chapter_post(tmp_path, colours=((200, 40, 40),))
    paths = PillowRenderer().render(post, {}, folder)
    assert _dominant(_pixel(paths[0], (540, 200))) == 0


def test_a_missing_panel_file_still_renders(tmp_path):
    post, folder = _chapter_post(tmp_path)
    (folder / post.chapter.panels[0]).unlink()
    paths = PillowRenderer().render(post, {}, folder)
    assert len(paths) == 4
    assert _pixel(paths[1], (20, 20)) != (0, 0, 0)


def test_rerendering_a_chapter_post_removes_stale_slides(tmp_path):
    post, folder = _chapter_post(tmp_path, colours=[(200, 40, 40)] * 5)
    PillowRenderer().render(post, {}, folder)
    shorter = post.model_copy(
        update={"chapter": post.chapter.model_copy(update={"panels": post.chapter.panels[:2]})}
    )
    PillowRenderer().render(shorter, {}, folder)
    assert sorted(p.name for p in folder.glob("[0-9][0-9].png")) == [
        "01.png",
        "02.png",
        "03.png",
        "04.png",
    ]


def test_a_chapter_post_writes_only_the_cover_version_it_uses(tmp_path):
    post, folder = _chapter_post(tmp_path)
    PillowRenderer().render(post, {}, folder)
    assert [p.name for p in sorted(folder.glob("cover-*.png"))] == ["cover-fan.png"]


def test_the_mark_is_the_handle_alone_when_a_post_carries_no_byline(tmp_path):
    from manhwatok.adapters.pillow_renderer import _byline

    assert _byline(_post(1).model_copy(update={"account": "reads"})) == "@reads"


def test_a_posts_own_byline_is_drawn_as_written(tmp_path):
    from manhwatok.adapters.pillow_renderer import _byline

    post = _post(1).model_copy(update={"account": "reads", "byline": "manhwa daily · @reads"})
    assert _byline(post) == "manhwa daily · @reads"


def test_a_byline_without_an_account_is_still_drawn(tmp_path):
    from manhwatok.adapters.pillow_renderer import _byline

    assert _byline(_post(1).model_copy(update={"byline": "manhwa daily"})) == "manhwa daily"


def _end_texts(tmp_path, monkeypatch, **fields):
    """The text the chapter end slide draws, in drawing order."""
    from manhwatok.adapters import pillow_renderer

    drawn = []
    real = pillow_renderer._draw_text

    def spy(draw, placed, color, accent):
        text = placed.text
        drawn.append(" ".join(text.line_text(i) for i in range(len(text.lines))))
        return real(draw, placed, color, accent)

    post, folder = _chapter_post(tmp_path, **fields)
    monkeypatch.setattr(pillow_renderer, "_draw_text", spy)
    paths = PillowRenderer().render(post, {}, folder)
    drawn.clear()  # the cover and panels are drawn first
    PillowRenderer().chapter_end_slide(post, None)
    return drawn, paths


def test_the_chapter_end_slide_names_the_title_then_what_ended_then_the_follow(
    tmp_path, monkeypatch
):
    drawn, _ = _end_texts(tmp_path, monkeypatch, number="12", part=1, parts=3)
    assert drawn == ["TEST MANHWA", "PART 2 NEXT", "FOLLOW FOR PART 2"]


def test_the_chapter_end_slide_asks_for_the_next_chapter_on_the_last_part(tmp_path, monkeypatch):
    drawn, _ = _end_texts(tmp_path, monkeypatch, number="12", part=3, parts=3)
    assert drawn == ["TEST MANHWA", "CHAPTER 12 DONE", "FOLLOW FOR CHAPTER 13"]


def test_the_chapter_end_slide_has_no_ranked_row(tmp_path, monkeypatch):
    drawn, _ = _end_texts(tmp_path, monkeypatch, number="12", part=3, parts=3)
    assert not any(text.strip().startswith("1 ") or " — CH." in text for text in drawn), drawn
