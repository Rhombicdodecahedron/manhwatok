import json

import pytest

pytest.importorskip("fastapi")

from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.models import CharacterPick, PostKind  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import FakeMetadata, manhwa  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402


def _ctx(tmp_path, n=4):
    meta = FakeMetadata(results=[manhwa(anilist_id=i, title=f"T{i}") for i in range(1, n + 1)])
    ctx = make_ctx(tmp_path, metadata=meta)
    ctx.store.accounts.add(Account(handle="reads"))
    return ctx, meta


def _draft(html: str) -> str:
    return html.split('name="draft" value="')[1].split('"')[0]


def _notice(response):
    return json.loads(response.headers["HX-Trigger"])["notice"]


@pytest.mark.parametrize("kind", ["similar", "versus", "guess", "characters"])
def test_every_kind_has_a_tab(tmp_path, kind):
    ctx, _ = _ctx(tmp_path)
    with client_for(ctx) as client:
        html = client.get(f"/new?type={kind}").text
    assert f'href="/new?type={kind}" aria-current="page"' in html


@pytest.mark.parametrize("kind", ["versus", "guess", "characters"])
def test_the_list_form_carries_the_kind(tmp_path, kind):
    ctx, _ = _ctx(tmp_path)
    with client_for(ctx) as client:
        html = client.get(f"/new?type={kind}").text
    assert f'<input type="hidden" name="kind" value="{kind}">' in html


def test_a_versus_search_saves_a_versus_post(tmp_path):
    ctx, _ = _ctx(tmp_path)
    with client_for(ctx) as client:
        html = client.post("/new/search", data={"kind": "versus", "tags": "Action", "limit": "4"}).text
        assert 'class="picks versus"' in html  # the picks show their pairing
        client.post(
            "/new/save",
            data={"draft": _draft(html), "title": "Which wins", "pick": ["1", "2", "3", "4"]},
        )
    (saved,) = ctx.tools.posts.list()
    assert saved.kind is PostKind.VERSUS and len(saved.items) == 4


def test_an_odd_versus_is_refused(tmp_path):
    ctx, _ = _ctx(tmp_path)
    with client_for(ctx) as client:
        html = client.post("/new/search", data={"kind": "versus", "tags": "Action", "limit": "3"}).text
        r = client.post("/new/save", data={"draft": _draft(html), "title": "X", "pick": ["1", "2", "3"]})
    assert "pairs" in _notice(r)["text"]
    assert ctx.tools.posts.list() == []


def test_a_similar_search_starts_from_the_seed(tmp_path):
    ctx, meta = _ctx(tmp_path)
    meta.recommended[1] = [manhwa(anilist_id=5, title="R5"), manhwa(anilist_id=6, title="R6")]
    with client_for(ctx) as client:
        html = client.post("/new/similar", data={"seed": "T1"}).text
        assert 'value="If you liked *T1*"' in html
        client.post(
            "/new/save", data={"draft": _draft(html), "title": "If you liked *T1*", "pick": ["5", "6"]}
        )
    (saved,) = ctx.tools.posts.list()
    assert saved.kind is PostKind.SIMILAR and saved.seed.title == "T1"
    assert [i.manhwa.title for i in saved.items] == ["R5", "R6"]


def test_a_similar_search_for_an_unknown_title_says_so(tmp_path):
    ctx, _ = _ctx(tmp_path)
    with client_for(ctx) as client:
        r = client.post("/new/similar", data={"seed": "Nothing like it"})
    assert _notice(r)["level"] == "error"


def test_a_characters_save_takes_the_chosen_character(tmp_path):
    ctx, meta = _ctx(tmp_path, 1)
    meta.cast[1] = [
        CharacterPick(name="Jin", index=0, image_url="u0"),
        CharacterPick(name="Hae", index=1, image_url="u1"),
    ]
    with client_for(ctx) as client:
        html = client.post("/new/search", data={"kind": "characters", "tags": "Action", "limit": "1"}).text
        assert ">Hae" in html  # the select lists the title's characters
        client.post(
            "/new/save",
            data={"draft": _draft(html), "title": "Top", "pick": ["1"], "character-1": "1"},
        )
    (saved,) = ctx.tools.posts.list()
    assert saved.kind is PostKind.CHARACTERS and saved.items[0].character.name == "Hae"


def test_the_post_detail_names_its_kind(tmp_path):
    from tests.unit.fakes import post

    ctx, _ = _ctx(tmp_path)
    ctx.tools.posts.save(post(kind=PostKind.GUESS))
    with client_for(ctx) as client:
        html = client.get("/posts/20260914-a3f9").text
    assert "guess post" in html


def _saved_kind(ctx, kind, items, candidates):
    from tests.unit.fakes import post

    ctx.tools.posts.save(post(items=items, candidates=candidates, kind=kind))
    return "20260914-a3f9"


def test_the_picks_editor_refuses_an_odd_versus_at_once(tmp_path):
    from manhwatok.domain.post import PostItem

    ctx, _ = _ctx(tmp_path)
    titles = [manhwa(anilist_id=i, title=f"T{i}") for i in range(1, 5)]
    pid = _saved_kind(ctx, PostKind.VERSUS, [PostItem(manhwa=m) for m in titles], titles)
    with client_for(ctx) as client:
        html = client.get(f"/posts/{pid}/picks").text
        r = client.post(f"/posts/{pid}/picks", data={"pick": ["1", "2", "3"]})
    assert 'class="picks versus"' in html
    assert "pairs" in _notice(r)["text"] and _notice(r)["level"] == "error"


def test_the_picks_editor_offers_and_keeps_a_characters_choice(tmp_path):
    from manhwatok.domain.post import PostItem

    ctx, meta = _ctx(tmp_path, 1)
    meta.cast[1] = [CharacterPick(name="Jin", index=0, image_url="u0"), CharacterPick(name="Hae", index=1, image_url="u1")]
    titles = [manhwa(anilist_id=1, title="T1")]
    item = PostItem(manhwa=titles[0], character=CharacterPick(name="Hae", index=1, image_url="u1"))
    pid = _saved_kind(ctx, PostKind.CHARACTERS, [item], titles)
    with client_for(ctx) as client:
        html = client.get(f"/posts/{pid}/picks").text
    assert '<option value="1" selected>Hae' in html
