import re
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from manhwatok.adapters.fs_posts import FsPostRepository
from manhwatok.adapters.sqlite_store import SqliteStore
from manhwatok.app import container
from manhwatok.app.post_tools import PostTools
from manhwatok.cli import app
from manhwatok.domain.account import Account
from manhwatok.domain.models import ArtStyle, Sort
from manhwatok.domain.theme import Theme
from tests.unit.fakes import (
    FakeChapters,
    FakeCovers,
    FakeMetadata,
    FakeRenderer,
    ScriptedEditor,
    manhwa,
    post,
)

runner = CliRunner()
CANDIDATES = [
    manhwa(anilist_id=11, title="Doom Breaker", description="Sent back ten years. More."),
    manhwa(anilist_id=22, title="Kubera", description="Gods. More."),
]


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("MANHWATOK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MANHWATOK_EXPORT_DIR", str(tmp_path / "exports"))


@pytest.fixture
def wire(tmp_path, monkeypatch):
    """Fake network, editor and renderer; real post folders under tmp_path."""

    def _wire(respond=lambda text: text + "\n", results=CANDIDATES, meta=None):
        editor = ScriptedEditor(respond)
        repo = FsPostRepository(tmp_path / "data" / "posts")
        meta = meta or FakeMetadata(results)
        monkeypatch.setattr(container, "build_metadata", lambda settings: meta)
        monkeypatch.setattr(
            container, "build_chapter_source", lambda settings, cache: FakeChapters({})
        )
        monkeypatch.setattr(
            container,
            "build_post_tools",
            lambda settings, _editor, progress: PostTools(
                repo,
                FakeCovers({11: tmp_path / "11.jpg", 22: tmp_path / "22.jpg"}),
                FakeRenderer(),
                editor,
                progress,
            ),
        )
        return repo, editor

    return _wire


def _store_posts(tmp_path) -> SqliteStore:
    return SqliteStore(tmp_path / "data" / "manhwatok.db")


def _post_id(output: str) -> str:
    return re.search(r"post (\d{8}-[0-9a-f]{4})", output).group(1)


def test_build_renders_and_prints_next_step(wire):
    repo, editor = wire()
    result = runner.invoke(
        app, ["build", "-t", "Revenge", "--title", "MC *regresses*", "--no-chapters"]
    )
    assert result.exit_code == 0, result.output
    post_id = _post_id(result.output)
    assert "· 4 slides →" in result.output
    assert f"export with: manhwatok export {post_id}" in result.output
    assert repo.get(post_id).title == "MC *regresses*"
    assert "title: MC *regresses*" in editor.shown[0]


def test_build_emojis_go_to_the_post_not_the_slides(wire):
    repo, _ = wire()
    args = ["build", "-t", "Revenge", "--title", "MC", "--emojis", "🔥", "--no-chapters"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    post_id = _post_id(result.output)
    assert (repo.get(post_id).title, repo.get(post_id).emojis) == ("MC", "🔥")
    assert (repo.folder(post_id) / "caption.txt").read_text().startswith("MC 🔥\n\n1. ")


def test_build_requires_a_filter(wire):
    wire()
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 1
    assert "at least one --tag or --genre" in result.output


def test_build_cancelled(wire):
    repo, _ = wire(respond=lambda text: None)
    result = runner.invoke(app, ["build", "-t", "Revenge"])
    assert result.exit_code == 0
    assert "cancelled — nothing saved" in result.output
    assert repo.list() == []


def test_build_bad_draft_exits_1_with_edit_hint(wire):
    wire(respond=lambda text: "title: T\n")
    result = runner.invoke(app, ["build", "-t", "Revenge"])
    assert result.exit_code == 1
    assert "error: no titles left" in result.output
    assert "fix with: manhwatok edit" in result.output


def test_build_bad_accent(wire):
    wire()
    result = runner.invoke(app, ["build", "-t", "Revenge", "--accent", "cyan"])
    assert result.exit_code == 1
    assert "accent must look like #43c9e4" in result.output


def test_edit_render_export_posts_flow(wire, tmp_path):
    repo, _ = wire(respond=lambda text: text.replace("Hook 1", "New hook"))
    repo.save(post())

    result = runner.invoke(app, ["edit", "20260914-a3f9"])
    assert result.exit_code == 0, result.output
    assert "post 20260914-a3f9 · 5 slides →" in result.output
    assert repo.get("20260914-a3f9").items[0].hook == "New hook"

    result = runner.invoke(app, ["render", "20260914-a3f9"])
    assert result.exit_code == 0, result.output
    assert "5 slides" in result.output

    result = runner.invoke(app, ["export", "20260914-a3f9"])
    assert result.exit_code == 0, result.output
    assert f"exported → {tmp_path / 'exports' / '20260914-a3f9'}" in result.output
    assert (tmp_path / "exports" / "20260914-a3f9" / "caption.txt").is_file()

    result = runner.invoke(app, ["export", "20260914-a3f9", "--out", str(tmp_path / "elsewhere")])
    assert result.exit_code == 0
    assert (tmp_path / "elsewhere" / "20260914-a3f9" / "05.png").is_file()


def test_edit_no_changes(wire):
    repo, _ = wire(respond=lambda text: None)
    repo.save(post())
    result = runner.invoke(app, ["edit", "20260914-a3f9"])
    assert result.exit_code == 0
    assert "no changes" in result.output


@pytest.mark.parametrize("command", ["edit", "render", "export"])
def test_unknown_post(wire, command):
    wire()
    result = runner.invoke(app, [command, "20260914-ffff"])
    assert result.exit_code == 1
    assert "error: no post 20260914-ffff" in result.output


def test_export_before_render(wire):
    repo, _ = wire()
    repo.save(post())
    result = runner.invoke(app, ["export", "20260914-a3f9"])
    assert result.exit_code == 1
    assert "run: manhwatok render 20260914-a3f9" in result.output


def test_export_destination_blocked_by_a_file_exits_1(wire, tmp_path):
    wire()
    built = runner.invoke(
        app, ["build", "-t", "Revenge", "--title", "MC *regresses*", "--no-chapters"]
    )
    post_id = _post_id(built.output)
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"not a directory")
    result = runner.invoke(app, ["export", post_id, "--out", str(blocker)])
    assert result.exit_code == 1
    assert result.output.startswith("error: ")


def test_posts_lists_newest_first_and_marks_drafts(wire):
    from datetime import datetime, timezone

    repo, _ = wire()
    repo.save(post(id="20260913-0001", created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    repo.save(
        post(
            id="20260914-0002",
            title="",
            items=[],
            created_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )
    )
    result = runner.invoke(app, ["posts"])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert lines[0].startswith("20260914-0002") and "draft" in lines[0] and "(untitled)" in lines[0]
    assert lines[1].startswith("20260913-0001") and "5 slides" in lines[1]
    assert "Manhwa where the MC regresses" in lines[1]


def test_posts_empty(wire):
    wire()
    result = runner.invoke(app, ["posts"])
    assert "no posts yet" in result.output


def test_help_lists_post_commands():
    result = runner.invoke(app, ["--help"])
    for command in ("build", "edit", "render", "export", "posts"):
        assert command in result.output


# --- accounts, themes, history, delete ---------------------------------------------------


def _store(tmp_path) -> SqliteStore:
    return SqliteStore(tmp_path / "data" / "manhwatok.db")


def _save(tmp_path, *items):
    with _store(tmp_path) as store:
        for item in items:
            (store.accounts if isinstance(item, Account) else store.themes).add(item)


REVENGE = Theme(
    name="revenge",
    tags=["Revenge"],
    genres=["Action"],
    sort=Sort.POPULARITY,
    min_tag_rank=75,
    title="MC gets *revenge*",
)


def test_build_from_a_theme(wire, tmp_path):
    meta = FakeMetadata(CANDIDATES)
    repo, editor = wire(meta=meta)
    _save(tmp_path, REVENGE)
    result = runner.invoke(app, ["build", "--theme", "Revenge", "-n", "5", "--no-chapters"])
    assert result.exit_code == 0, result.output
    [q] = meta.queries
    assert (q.tags, q.genres, q.sort, q.min_tag_rank, q.limit) == (
        ["Revenge"],
        ["Action"],
        Sort.POPULARITY,
        75,
        5,
    )
    assert "title: MC gets *revenge*" in editor.shown[0]
    assert repo.get(_post_id(result.output)).account is None


def test_build_flags_override_the_theme(wire, tmp_path):
    meta = FakeMetadata(CANDIDATES)
    _, editor = wire(meta=meta)
    _save(tmp_path, REVENGE)
    args = ["build", "--theme", "revenge", "--title", "Other", "--sort", "score"]
    result = runner.invoke(app, args + ["--min-tag-rank", "50", "--no-chapters"])
    assert result.exit_code == 0, result.output
    assert (meta.queries[0].sort, meta.queries[0].min_tag_rank) == (Sort.SCORE, 50)
    assert "title: Other" in editor.shown[0]


def test_build_theme_and_tags_conflict(wire, tmp_path):
    wire()
    _save(tmp_path, REVENGE)
    result = runner.invoke(app, ["build", "--theme", "revenge", "-t", "Revenge"])
    assert result.exit_code == 1
    assert "error: use either --theme or -t/-g, not both" in result.output


def test_build_unknown_theme(wire):
    wire()
    result = runner.invoke(app, ["build", "--theme", "nope"])
    assert result.exit_code == 1
    assert "error: no theme nope" in result.output


def test_build_for_an_account_uses_its_filters_style_and_history(wire, tmp_path):
    meta = FakeMetadata(CANDIDATES)
    repo, editor = wire(respond=lambda text: text, meta=meta)
    _save(tmp_path, Account(handle="reads", block_genres=["Romance"], hashtags="#reads"))
    with _store(tmp_path) as store:
        store.history.record("reads", "20260901-0001", [22], datetime.now(timezone.utc))
    args = ["build", "-a", "@reads", "-t", "Revenge", "--title", "T", "--no-chapters"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert meta.queries[0].exclude_genres == ["Romance"]
    assert "Kubera" not in editor.shown[0]
    assert "skipping 1 title(s) @reads" in result.output
    built = repo.get(_post_id(result.output))
    assert (built.account, built.hashtags) == ("reads", "#reads")


def test_build_allow_repeats_keeps_recent_titles(wire, tmp_path):
    _, editor = wire(respond=lambda text: text)
    _save(tmp_path, Account(handle="reads"))
    with _store(tmp_path) as store:
        store.history.record("reads", "20260901-0001", [22], datetime.now(timezone.utc))
    args = ["build", "-a", "reads", "-t", "Revenge", "--title", "T", "--allow-repeats"]
    result = runner.invoke(app, args + ["--no-chapters"])
    assert result.exit_code == 0, result.output
    assert "Kubera" in editor.shown[0]


def test_build_unknown_account(wire):
    wire()
    result = runner.invoke(app, ["build", "-a", "ghost", "-t", "Revenge"])
    assert result.exit_code == 1
    assert "error: no account @ghost" in result.output


def test_export_of_an_account_post_counts_its_titles_as_posted(wire, tmp_path):
    wire(respond=lambda text: text)
    _save(tmp_path, Account(handle="reads"))
    args = ["build", "-a", "reads", "-t", "Revenge", "--title", "T", "--no-chapters"]
    built = runner.invoke(app, args)
    post_id = _post_id(built.output)
    result = runner.invoke(app, ["export", post_id])
    assert result.exit_code == 0, result.output
    with _store(tmp_path) as store:
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        assert store.history.recent("reads", since) == {11, 22}


def test_suggest_for_an_account_skips_recent_titles(wire, tmp_path):
    meta = FakeMetadata(CANDIDATES)
    wire(meta=meta)
    _save(tmp_path, Account(handle="reads", block_tags=["Harem"]))
    with _store(tmp_path) as store:
        store.history.record("reads", "20260901-0001", [11], datetime.now(timezone.utc))
    result = runner.invoke(app, ["suggest", "-a", "reads", "-t", "Revenge", "--no-chapters"])
    assert result.exit_code == 0, result.output
    assert "Doom Breaker" not in result.output
    assert " 1. Kubera" in result.output
    assert meta.queries[0].exclude_tags == ["Harem"]


def test_posts_show_and_filter_by_account(wire):
    repo, _ = wire()
    repo.save(post(id="20260913-0001", created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    repo.save(
        post(
            id="20260914-0002",
            account="reads",
            created_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )
    )
    lines = runner.invoke(app, ["posts"]).output.strip().splitlines()
    assert re.match(r"20260914-0002  \S+ \S+  @reads   5 slides  Manhwa", lines[0])
    assert re.match(r"20260913-0001  \S+ \S+  -        5 slides  Manhwa", lines[1])
    only = runner.invoke(app, ["posts", "--account", "@READS"]).output.strip().splitlines()
    assert [line[:13] for line in only] == ["20260914-0002"]
    assert "no posts for @other yet" in runner.invoke(app, ["posts", "-a", "other"]).output


def test_delete_asks_first(wire):
    repo, _ = wire()
    repo.save(post())
    result = runner.invoke(app, ["delete", "20260914-a3f9"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Delete post 20260914-a3f9 (5 slides)? [y/N]" in result.output
    assert "kept" in result.output
    assert repo.folder("20260914-a3f9").exists()

    result = runner.invoke(app, ["delete", "20260914-a3f9"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "deleted post 20260914-a3f9" in result.output
    assert not repo.folder("20260914-a3f9").exists()


def test_delete_yes_skips_the_question(wire):
    repo, _ = wire()
    repo.save(post(items=[]))
    result = runner.invoke(app, ["delete", "20260914-a3f9", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Delete post" not in result.output
    assert not repo.folder("20260914-a3f9").exists()


def test_delete_an_empty_leftover_folder(wire):
    """A build that died right after reserving its id leaves a folder with no post in it."""
    repo, _ = wire()
    leftover = repo.new_id(datetime(2026, 9, 14).date())
    result = runner.invoke(app, ["delete", leftover], input="n\n")
    assert result.exit_code == 0, result.output
    assert f"Delete post {leftover} (empty)? [y/N]" in result.output
    assert repo.folder(leftover).is_dir()

    result = runner.invoke(app, ["delete", leftover, "--yes"])
    assert result.exit_code == 0, result.output
    assert f"deleted post {leftover}" in result.output
    assert not repo.folder(leftover).exists()


def test_delete_an_unreadable_post(wire):
    repo, _ = wire()
    repo.folder("20260914-a3f9").mkdir(parents=True)
    (repo.folder("20260914-a3f9") / "post.json").write_text("{not json")
    result = runner.invoke(app, ["delete", "20260914-a3f9"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "Delete post 20260914-a3f9 (unreadable)? [y/N]" in result.output
    assert not repo.folder("20260914-a3f9").exists()


def test_delete_unknown_post(wire):
    wire()
    result = runner.invoke(app, ["delete", "20260914-ffff", "--yes"])
    assert result.exit_code == 1
    assert "error: no post 20260914-ffff" in result.output
    result = runner.invoke(app, ["delete", "../etc", "--yes"])
    assert result.exit_code == 1
    assert "error: '../etc' is not a post id" in result.output


def test_help_lists_delete():
    assert "delete" in runner.invoke(app, ["--help"]).output


def test_posts_marks_sent_posts(wire):
    repo, _ = wire()
    repo.save(post(id="20260913-0001", created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    repo.save(
        post(
            id="20260914-0002",
            account="reads",
            created_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
            sent_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
        )
    )
    lines = runner.invoke(app, ["posts"]).output.strip().splitlines()
    assert re.match(r"20260914-0002  \S+ \S+  @reads   5 slides  sent  Manhwa", lines[0])
    assert re.match(r"20260913-0001  \S+ \S+  -        5 slides        Manhwa", lines[1])


# --- --art (Phase 5) -------------------------------------------------------------------------


def test_build_art_flag_is_saved_on_the_post(wire):
    repo, _ = wire()
    out = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters", "--art", "background"])
    assert out.exit_code == 0, out.output
    assert repo.get(_post_id(out.output)).art is ArtStyle.BACKGROUND


def test_build_takes_art_from_the_account_and_the_flag_overrides_it(wire, tmp_path):
    repo, _ = wire()
    with _store_posts(tmp_path) as store:
        store.accounts.add(Account(handle="reads", art=ArtStyle.BACKGROUND))
    from_account = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters", "--account", "@reads"])
    assert from_account.exit_code == 0, from_account.output
    assert repo.get(_post_id(from_account.output)).art is ArtStyle.BACKGROUND

    overridden = runner.invoke(
        app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters", "--account", "@reads", "--art", "none"]
    )
    assert overridden.exit_code == 0, overridden.output
    assert repo.get(_post_id(overridden.output)).art is ArtStyle.NONE


def test_render_art_flag_restyles_an_existing_post(wire):
    repo, _ = wire()
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    post_id = _post_id(built.output)
    assert repo.get(post_id).art is ArtStyle.NONE
    out = runner.invoke(app, ["render", post_id, "--art", "background"])
    assert out.exit_code == 0, out.output
    assert repo.get(post_id).art is ArtStyle.BACKGROUND


def test_render_without_the_flag_keeps_the_posts_art(wire):
    repo, _ = wire()
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters", "--art", "background"])
    post_id = _post_id(built.output)
    assert runner.invoke(app, ["render", post_id]).exit_code == 0
    assert repo.get(post_id).art is ArtStyle.BACKGROUND


def test_build_rejects_an_unknown_art_style(wire):
    wire()
    out = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters", "--art", "epic"])
    assert out.exit_code != 0
    assert "background" in out.output  # the error names the styles that do exist


# --- art <post> <title> <file> ----------------------------------------------------------------


def _pick_file(tmp_path, name="pick.png"):
    path = tmp_path / name
    path.write_bytes(b"\x89PNG pretend")
    return path


def test_art_attaches_a_file_to_one_title_and_rerenders(wire, tmp_path):
    repo, _ = wire()
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    post_id = _post_id(built.output)
    out = runner.invoke(app, ["art", post_id, "11", str(_pick_file(tmp_path))])
    assert out.exit_code == 0, out.output
    item = next(i for i in repo.get(post_id).items if i.manhwa.anilist_id == 11)
    assert item.custom_art == "art-11.png"
    assert (repo.folder(post_id) / "art-11.png").is_file()
    assert "slides" in out.output  # it re-rendered


def test_art_clear_removes_it(wire, tmp_path):
    repo, _ = wire()
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    post_id = _post_id(built.output)
    runner.invoke(app, ["art", post_id, "11", str(_pick_file(tmp_path))])
    out = runner.invoke(app, ["art", post_id, "11", "--clear"])
    assert out.exit_code == 0, out.output
    item = next(i for i in repo.get(post_id).items if i.manhwa.anilist_id == 11)
    assert item.custom_art == ""
    assert not (repo.folder(post_id) / "art-11.png").exists()


def test_art_without_a_file_or_clear_fails(wire):
    wire()
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    out = runner.invoke(app, ["art", _post_id(built.output), "11"])
    assert out.exit_code != 0
    assert "--clear" in out.output


def test_art_on_an_unknown_title_lists_the_ones_in_the_post(wire, tmp_path):
    wire()
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    out = runner.invoke(app, ["art", _post_id(built.output), "999", str(_pick_file(tmp_path))])
    assert out.exit_code != 0
    assert "Doom Breaker" in out.output


def test_art_downloads_a_url(wire, monkeypatch):
    import httpx

    from manhwatok.adapters import picture_download

    def host(request):
        return httpx.Response(200, content=b"\x89PNG pretend", headers={"Content-Type": "image/png"})

    real = picture_download.download_picture
    monkeypatch.setattr(
        picture_download,
        "download_picture",
        lambda url, into, **kw: real(
            url, into, client=httpx.Client(transport=httpx.MockTransport(host))
        ),
    )
    repo, _ = wire()
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    post_id = _post_id(built.output)
    out = runner.invoke(app, ["art", post_id, "11", "https://example.test/cool.png"])
    assert out.exit_code == 0, out.output
    item = next(i for i in repo.get(post_id).items if i.manhwa.anilist_id == 11)
    assert item.custom_art == "art-11.png"
    assert (repo.folder(post_id) / "art-11.png").read_bytes() == b"\x89PNG pretend"


def test_art_expands_a_tilde_path(wire, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    pick = tmp_path / "pick.png"
    pick.write_bytes(b"\x89PNG pretend")
    repo, _ = wire()
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    post_id = _post_id(built.output)
    out = runner.invoke(app, ["art", post_id, "11", "~/pick.png"])
    assert out.exit_code == 0, out.output
    assert repo.get(post_id).items[0].custom_art == "art-11.png"


def _wire_art(monkeypatch, options=None, error=None, fanart=None):
    """Point the CLI's art sources at scripted ones; returns (covers, fanart)."""
    from manhwatok.domain.models import ArtSourceName
    from tests.unit.fakes import FakeArtSource

    covers = FakeArtSource(options, error)
    fan = FakeArtSource(fanart or {})
    monkeypatch.setattr(
        container,
        "build_art_sources",
        lambda settings, cache: {
            ArtSourceName.COVERS: covers,
            ArtSourceName.FANART: fan,
        },
    )
    return covers, fan


def test_art_list_shows_the_numbered_covers_the_source_has(wire, monkeypatch):
    from manhwatok.ports.art import ArtOption

    wire()
    _wire_art(monkeypatch, {11: [ArtOption("vol. 1", "https://x.test/1.jpg"),
                                 ArtOption("vol. 2", "https://x.test/2.jpg")]})
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    out = runner.invoke(app, ["art", _post_id(built.output), "11", "--list"])

    assert out.exit_code == 0, out.output
    assert "1  vol. 1" in out.output
    assert "2  vol. 2" in out.output


def test_art_list_says_so_when_the_source_has_nothing(wire, monkeypatch):
    wire()
    _wire_art(monkeypatch, {})
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    out = runner.invoke(app, ["art", _post_id(built.output), "11", "--list"])

    assert out.exit_code == 0, out.output
    assert "no covers" in out.output.lower()


def test_art_pick_downloads_that_cover_and_uses_it(wire, monkeypatch):
    from manhwatok.ports.art import ArtOption

    repo, _ = wire()
    source, _ = _wire_art(monkeypatch, {11: [ArtOption("vol. 1", "https://x.test/1.jpg"),
                                             ArtOption("vol. 2", "https://x.test/2.jpg")]})
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    post_id = _post_id(built.output)
    out = runner.invoke(app, ["art", post_id, "11", "--pick", "2"])

    assert out.exit_code == 0, out.output
    assert source.fetched == ["https://x.test/2.jpg"]
    item = next(i for i in repo.get(post_id).items if i.manhwa.anilist_id == 11)
    assert item.custom_art == "art-11.jpg"


def test_art_pick_out_of_range_says_the_range_instead_of_crashing(wire, monkeypatch):
    from manhwatok.ports.art import ArtOption

    wire()
    source, _ = _wire_art(monkeypatch, {11: [ArtOption("vol. 1", "https://x.test/1.jpg")]})
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    out = runner.invoke(app, ["art", _post_id(built.output), "11", "--pick", "7"])

    assert out.exit_code == 1, out.output
    assert out.exception is None or isinstance(out.exception, SystemExit)
    assert "no cover 7" in out.output and "1-1" in out.output
    assert source.fetched == []


def test_art_rejects_pick_together_with_a_file(wire, monkeypatch, tmp_path):
    from manhwatok.ports.art import ArtOption

    wire()
    # A cover that --pick 1 would happily use, so only the conflict itself can fail this.
    source, _ = _wire_art(monkeypatch, {11: [ArtOption("vol. 1", "https://x.test/1.jpg")]})
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    out = runner.invoke(
        app, ["art", _post_id(built.output), "11", str(_pick_file(tmp_path)), "--pick", "1"]
    )

    assert out.exit_code == 1, out.output
    assert "exactly one of" in out.output
    assert "a picture, --pick" in out.output
    assert source.fetched == []


def test_art_list_source_fanart_asks_the_fan_art_source(wire, monkeypatch):
    from manhwatok.ports.art import ArtOption

    wire()
    _wire_art(
        monkeypatch,
        {11: [ArtOption("vol. 1", "https://x.test/1.jpg")]},
        fanart={11: [ArtOption("\u2605 99  900x1400  by someone", "https://x.test/fan.jpg")]},
    )
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    out = runner.invoke(app, ["art", _post_id(built.output), "11", "--list", "--source", "fanart"])

    assert out.exit_code == 0, out.output
    assert "by someone" in out.output
    assert "vol. 1" not in out.output


def test_art_pick_source_fanart_downloads_from_the_fan_art_source(wire, monkeypatch):
    from manhwatok.ports.art import ArtOption

    wire()
    covers, fan = _wire_art(
        monkeypatch,
        {11: [ArtOption("vol. 1", "https://x.test/1.jpg")]},
        fanart={11: [ArtOption("\u2605 99  900x1400  by someone", "https://x.test/fan.jpg")]},
    )
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    out = runner.invoke(
        app, ["art", _post_id(built.output), "11", "--pick", "1", "--source", "fanart"]
    )

    assert out.exit_code == 0, out.output
    assert fan.fetched == ["https://x.test/fan.jpg"]
    assert covers.fetched == []


def test_art_defaults_to_covers_when_no_source_is_given(wire, monkeypatch):
    from manhwatok.ports.art import ArtOption

    wire()
    covers, fan = _wire_art(
        monkeypatch,
        {11: [ArtOption("vol. 1", "https://x.test/1.jpg")]},
        fanart={11: [ArtOption("fan", "https://x.test/fan.jpg")]},
    )
    built = runner.invoke(app, ["build", "-t", "Revenge", "--title", "T", "--no-chapters"])
    out = runner.invoke(app, ["art", _post_id(built.output), "11", "--pick", "1"])

    assert out.exit_code == 0, out.output
    assert covers.fetched == ["https://x.test/1.jpg"]
    assert fan.fetched == []
