import pytest
from PIL import Image

from manhwatok.adapters.pillow_renderer import PillowRenderer
from manhwatok.domain.color import hex_to_rgb, readable_accent
from manhwatok.domain.errors import StorageError
from manhwatok.domain.models import ArtStyle
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
    assert sorted(x.name for x in out.glob("*.png")) == ["01.png", "02.png", "03.png"]


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

    def spy(names, cta_title, cta_follow):
        seen.append((names, cta_title, cta_follow))
        return real(names, cta_title, cta_follow)

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
