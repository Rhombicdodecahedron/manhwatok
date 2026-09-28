from manhwatok.domain.models import CharacterPick, PostKind
from tests.unit.fakes import FakeMetadata, manhwa
from tests.unit.test_cli_posts import CANDIDATES, _post_id, app, runner, wire  # noqa: F401


def test_build_kind_versus_makes_a_versus_post(wire):  # noqa: F811
    repo, _ = wire()
    out = runner.invoke(app, ["build", "-t", "Revenge", "--kind", "versus", "--title", "Who *wins*", "--no-chapters"])
    assert out.exit_code == 0, out.output
    saved = repo.get(_post_id(out.output))
    assert saved.kind is PostKind.VERSUS and len(saved.items) == 2
    assert "· 3 slides →" in out.output  # cover, one round, end


def test_build_kind_chapter_points_to_chapter_build(wire):  # noqa: F811
    wire()
    out = runner.invoke(app, ["build", "-t", "Revenge", "--kind", "chapter"])
    assert out.exit_code == 1 and "chapter build" in out.output


def test_build_like_makes_a_similar_post(wire):  # noqa: F811
    meta = FakeMetadata(CANDIDATES)
    meta.recommended[11] = [manhwa(anilist_id=33, title="R33"), manhwa(anilist_id=44, title="R44")]
    repo, editor = wire(meta=meta)
    out = runner.invoke(app, ["build", "--like", "Doom Breaker", "--no-chapters"])
    assert out.exit_code == 0, out.output
    saved = repo.get(_post_id(out.output))
    assert saved.kind is PostKind.SIMILAR and saved.seed.title == "Doom Breaker"
    assert saved.title == "If you liked *Doom Breaker*"
    assert [i.manhwa.title for i in saved.items] == ["R33", "R44"]


def test_build_characters_takes_the_numbered_character(wire):  # noqa: F811
    meta = FakeMetadata(CANDIDATES)
    meta.cast[11] = [CharacterPick(name="Zeph", index=0, image_url="u0"), CharacterPick(name="Ria", index=1, image_url="u1")]
    meta.cast[22] = [CharacterPick(name="Leez", index=0, image_url="u2")]

    def respond(text):
        return text.replace("| Sent back ten years.", "| Sent back ten years. | 2")

    repo, editor = wire(respond=respond, meta=meta)
    out = runner.invoke(app, ["build", "-t", "Revenge", "--kind", "characters", "--title", "Top", "--no-chapters"])
    assert out.exit_code == 0, out.output
    saved = repo.get(_post_id(out.output))
    assert [i.character.name for i in saved.items] == ["Ria", "Leez"]
    assert "Zeph, Ria" in editor.shown[0]  # the draft lists each title's characters


def test_parse_choices_reads_the_fourth_field():
    from manhwatok.domain.draft import parse_choices

    assert parse_choices("title: T\n1 | T1 | hook | 2\n3 | T3 | h\n# 4 | x | y | 3\n") == {1: 1}


def test_a_fourth_field_stays_out_of_the_hook():
    from manhwatok.domain.draft import parse_draft

    _, items = parse_draft("title: T\n1 | T1 | hook | 2\n", [manhwa(anilist_id=1, title="T1")])
    assert items[0].hook == "hook"


def test_a_hook_with_a_pipe_keeps_its_words_and_is_no_choice():
    from manhwatok.domain.draft import parse_choices, parse_draft

    text = "title: T\n1 | T1 | Win | or lose\n"
    _, items = parse_draft(text, [manhwa(anilist_id=1, title="T1")])
    assert items[0].hook == "Win | or lose" and parse_choices(text) == {}


def test_a_rescued_draft_keeps_its_kind(wire):  # noqa: F811
    meta = FakeMetadata(CANDIDATES)
    meta.cast[11] = [CharacterPick(name="Zeph", index=0, image_url="u0")]  # Kubera has none
    repo, _ = wire(meta=meta)
    out = runner.invoke(app, ["build", "-t", "Revenge", "--kind", "characters", "--title", "Top", "--no-chapters"])
    assert out.exit_code == 1 and "Kubera has no pictured characters" in out.output
    (saved,) = repo.list()
    assert saved.kind is PostKind.CHARACTERS


def test_an_odd_versus_draft_is_saved_not_lost(wire):  # noqa: F811
    def respond(text):
        return "\n".join("# " + line if line.startswith("22 |") else line for line in text.splitlines()) + "\n"

    repo, _ = wire(respond=respond)
    out = runner.invoke(app, ["build", "-t", "Revenge", "--kind", "versus", "--title", "V", "--no-chapters"])
    assert out.exit_code == 1 and "pairs" in out.output and "draft is saved" in out.output
    (saved,) = repo.list()
    assert saved.kind is PostKind.VERSUS and repo.load_draft(saved.id)
