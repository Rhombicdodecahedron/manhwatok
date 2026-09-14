from PIL import Image

from manhwatok.adapters.pillow_renderer import PillowRenderer
from manhwatok.domain.color import hex_to_rgb, readable_accent
from manhwatok.domain.post import PostItem
from tests.unit.fakes import cover_file, manhwa, post


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
    paths = PillowRenderer().render(p, covers, tmp_path / "out")
    assert [x.name for x in paths] == ["01.png", "02.png", "03.png", "04.png", "05.png"]
    for x in paths:
        with Image.open(x) as img:
            assert img.size == (1080, 1920)
            assert img.mode == "RGB"


def test_rerender_removes_stale_slides(tmp_path):
    out = tmp_path / "out"
    covers = {i: cover_file(tmp_path / "covers", i) for i in (1, 2, 3)}
    PillowRenderer().render(_post(3), covers, out)
    PillowRenderer().render(_post(1), covers, out)
    assert sorted(x.name for x in out.glob("*.png")) == ["01.png", "02.png", "03.png"]


def test_missing_or_broken_cover_still_renders(tmp_path):
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    paths = PillowRenderer().render(_post(2), {1: None, 2: broken}, tmp_path / "out")
    assert len(paths) == 4


def test_single_item_post(tmp_path):
    paths = PillowRenderer().render(_post(1), {1: cover_file(tmp_path, 1)}, tmp_path / "out")
    assert len(paths) == 3


def test_manhwa_slide_uses_readable_accent_for_rank(tmp_path):
    """#6b1a1a is too dark; the rank number must be drawn in a lightened red, not the raw colour."""
    PillowRenderer().render(
        _post(1), {1: cover_file(tmp_path, 1, color=(20, 20, 20))}, tmp_path / "out"
    )
    with Image.open(tmp_path / "out" / "02.png") as img:
        colors = {c for _, c in img.getcolors(maxcolors=1 << 20)}
    assert (0x6B, 0x1A, 0x1A) not in colors
    assert hex_to_rgb(readable_accent("#6b1a1a")) in colors
