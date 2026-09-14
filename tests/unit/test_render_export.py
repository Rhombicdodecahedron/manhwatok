import pytest

from manhwatok.adapters.pillow_renderer import PillowRenderer
from manhwatok.app.export_post import export_post
from manhwatok.app.render_post import render_post
from manhwatok.domain.errors import DraftError, NotRendered, PostNotFound
from tests.unit.fakes import FakeCovers, cover_file, make_tools, post


# --- render ------------------------------------------------------------------------------


def test_render_writes_slides_and_caption(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    slides = render_post("20260914-a3f9", tools)
    folder = tools.posts.folder("20260914-a3f9")
    assert [s.name for s in slides] == ["01.png", "02.png", "03.png", "04.png", "05.png"]
    assert (
        (folder / "caption.txt")
        .read_text()
        .startswith("Manhwa where the MC regresses\n\n1. Title 1")
    )
    _, covers = tools.renderer.calls[0]
    assert covers == {1: tmp_path / "1.jpg", 2: tmp_path / "2.jpg", 3: tmp_path / "3.jpg"}


def test_render_stops_downloading_after_first_cover_failure(tmp_path):
    messages = []
    covers = FakeCovers({1: tmp_path / "1.jpg", 3: tmp_path / "3.jpg"}, fail={2})
    tools = make_tools(tmp_path, covers=covers, messages=messages)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    _, passed = tools.renderer.calls[0]
    assert passed == {1: tmp_path / "1.jpg", 2: None, 3: None}
    assert covers.calls == [1, 2]
    assert len(messages) == 1
    assert "plain backgrounds" in messages[0]


def test_render_unfinished_post(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(items=[]))
    with pytest.raises(DraftError, match="fix with: manhwatok edit 20260914-a3f9"):
        render_post("20260914-a3f9", tools)


def test_render_unknown_post(tmp_path):
    with pytest.raises(PostNotFound):
        render_post("20260914-ffff", make_tools(tmp_path))


def test_render_with_real_renderer(tmp_path):
    covers = FakeCovers({i: cover_file(tmp_path / "covers", i) for i in (1, 2, 3)})
    tools = make_tools(tmp_path, covers=covers, renderer=PillowRenderer())
    tools.posts.save(post())
    assert len(render_post("20260914-a3f9", tools)) == 5


# --- export ------------------------------------------------------------------------------


def test_export_copies_slides_and_caption(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    dest = export_post("20260914-a3f9", tools.posts, tmp_path / "exports")
    assert dest == tmp_path / "exports" / "20260914-a3f9"
    assert sorted(f.name for f in dest.iterdir()) == [
        "01.png",
        "02.png",
        "03.png",
        "04.png",
        "05.png",
        "caption.txt",
    ]


def test_export_replaces_stale_slides_in_destination(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    render_post("20260914-a3f9", tools)
    stale = tmp_path / "exports" / "20260914-a3f9"
    stale.mkdir(parents=True)
    (stale / "09.png").write_bytes(b"old")
    export_post("20260914-a3f9", tools.posts, tmp_path / "exports")
    assert not (stale / "09.png").exists()


def test_export_before_render(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post())
    with pytest.raises(NotRendered, match="run: manhwatok render 20260914-a3f9"):
        export_post("20260914-a3f9", tools.posts, tmp_path / "exports")


def test_export_unfinished_post(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(items=[]))
    with pytest.raises(DraftError):
        export_post("20260914-a3f9", tools.posts, tmp_path / "exports")
