import pytest

from manhwatok.app.edit_post import update_post_texts
from manhwatok.domain.errors import DraftError, InvalidName
from manhwatok.domain.post import DEFAULT_CTA_FOLLOW
from tests.unit.fakes import make_tools, post

PID = "20260926-0001"


def _tools(tmp_path):
    tools = make_tools(tmp_path)
    tools.posts.save(post(id=PID))
    return tools


def test_texts_are_saved_stripped(tmp_path):
    tools = _tools(tmp_path)
    saved = update_post_texts(PID, {
        "title": "  New *title* ", "hashtags": "#a #b", "emojis": "🔥", "byline": "@me",
        "cta_title": "Read *which*?", "cta_follow": " Follow! ", "accent": "#FF5588",
    }, tools)
    again = tools.posts.get(PID)
    assert saved == again
    assert (again.title, again.hashtags, again.emojis, again.byline) == (
        "New *title*", "#a #b", "🔥", "@me")
    assert (again.cta_title, again.cta_follow, again.accent) == (
        "Read *which*?", "Follow!", "#ff5588"
    )


def test_only_the_given_fields_change(tmp_path):
    tools = _tools(tmp_path)
    before = tools.posts.get(PID)
    update_post_texts(PID, {"emojis": "📚"}, tools)
    after = tools.posts.get(PID)
    assert after.emojis == "📚" and after.title == before.title and after.items == before.items


def test_a_blank_end_slide_text_goes_back_to_the_default(tmp_path):
    tools = _tools(tmp_path)
    update_post_texts(PID, {"cta_follow": "  "}, tools)
    assert tools.posts.get(PID).cta_follow == DEFAULT_CTA_FOLLOW


@pytest.mark.parametrize(
    ("changes", "error"),
    [({"title": " "}, DraftError), ({"accent": "blue"}, InvalidName), ({"items": "x"}, ValueError)],
)
def test_bad_texts_change_nothing(tmp_path, changes, error):
    tools = _tools(tmp_path)
    before = tools.posts.get(PID)
    with pytest.raises(error):
        update_post_texts(PID, changes, tools)
    assert tools.posts.get(PID) == before
