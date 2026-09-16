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
