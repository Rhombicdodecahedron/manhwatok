from manhwatok.app.hooks import hook_for
from manhwatok.domain.text import HOOK_MAX, first_sentence
from tests.unit.fakes import FakeCache, FakeWriter, make_tools, manhwa

LONG = "A boy enters a tower that " + "really " * 20 + "tests him. Then more happens."
TITLE = manhwa(anilist_id=7, title="Tower Climber", description=LONG)
CUT = first_sentence(LONG)  # today's hook: the first sentence, cut off


def test_without_a_writer_the_hook_is_the_cut_first_sentence(tmp_path):
    assert CUT.endswith("really…") and len(CUT) <= HOOK_MAX
    assert hook_for(TITLE, make_tools(tmp_path)) == CUT


def test_the_writers_hook_replaces_the_cut(tmp_path):
    writer = FakeWriter("A boy climbs a tower that tests him.")
    assert hook_for(TITLE, make_tools(tmp_path, writer=writer)) == "A boy climbs a tower that tests him."
    assert writer.asked == [(7, HOOK_MAX)]


def test_a_hook_too_long_for_the_slide_is_asked_for_again_shorter(tmp_path):
    writer = FakeWriter("x" * (HOOK_MAX + 1), "Short enough.")
    assert hook_for(TITLE, make_tools(tmp_path, writer=writer)) == "Short enough."
    assert [max_len for _, max_len in writer.asked] == [HOOK_MAX, HOOK_MAX - 20]


def test_a_writer_that_keeps_running_long_gets_the_cut(tmp_path):
    writer = FakeWriter("x" * 200, "y" * 200, "never asked")
    assert hook_for(TITLE, make_tools(tmp_path, writer=writer)) == CUT
    assert len(writer.asked) == 2


def test_a_hook_that_trails_off_is_not_kept(tmp_path):
    for trailing in ("A boy climbs…", "A boy climbs..."):
        writer = FakeWriter(trailing, trailing)
        assert hook_for(TITLE, make_tools(tmp_path, writer=writer)) == CUT


def test_a_writer_with_nothing_to_say_is_not_asked_twice(tmp_path):
    writer = FakeWriter(None, "too late")
    assert hook_for(TITLE, make_tools(tmp_path, writer=writer)) == CUT
    assert len(writer.asked) == 1


def test_a_written_hook_is_kept_for_the_title(tmp_path):
    cache = FakeCache()
    first = FakeWriter("Written once.")
    assert hook_for(TITLE, make_tools(tmp_path, writer=first, cache=cache)) == "Written once."

    again = FakeWriter("Written twice.")
    assert hook_for(TITLE, make_tools(tmp_path, writer=again, cache=cache)) == "Written once."
    assert again.asked == []


def test_another_model_writes_its_own_hook(tmp_path):
    cache = FakeCache()
    hook_for(TITLE, make_tools(tmp_path, writer=FakeWriter("By one model."), cache=cache))
    other = FakeWriter("By another.")
    other.model = "other"
    assert hook_for(TITLE, make_tools(tmp_path, writer=other, cache=cache)) == "By another."


def test_the_cut_is_never_kept_so_a_writer_back_up_gets_its_turn(tmp_path):
    cache = FakeCache()
    assert hook_for(TITLE, make_tools(tmp_path, writer=FakeWriter(None), cache=cache)) == CUT
    back = FakeWriter("Back up.")
    assert hook_for(TITLE, make_tools(tmp_path, writer=back, cache=cache)) == "Back up."


def test_a_cache_that_fails_does_not_stop_the_hook(tmp_path):
    from manhwatok.domain.errors import ManhwatokError

    class Broken:
        def get(self, key, max_age):
            raise ManhwatokError("database is unusable")

        def put(self, key, value):
            raise ManhwatokError("database is unusable")

    tools = make_tools(tmp_path, writer=FakeWriter("Still written."), cache=Broken())
    assert hook_for(TITLE, tools) == "Still written."
