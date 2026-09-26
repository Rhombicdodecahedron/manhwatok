# Web app, step 3: edit a post — texts, look, picks, art — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From a post in the web app, change anything about it: its texts (title, hashtags, emojis, byline, end-slide texts), its look (accent, art style, cover style), its picks (add, drop, reorder, hooks), and each title's picture (from MangaDex covers, fanart, Pinterest, Reddit, a URL or a file), or fill every title from a source at once — each change re-rendering the post.

**Architecture:** A new Edit page per post (`/posts/{id}/edit`) with four sections. Every change runs through the same `app/` functions as the TUI and CLI (`update_picks`, `list_art`, `use_art`, `set_item_art`, `clear_item_art`, `restyle`, `set_cover`, `render_from_source`, `render_post`) plus one new app function for texts, `update_post_texts`. Changes that download or render run in the render lane as one job ("change, then render"); a busy render lane refuses them with a notice, as step 1 does. Art options found for a title are kept server-side (`ArtLists`, like `Drafts`) between listing and choosing.

**Tech Stack:** as steps 1–2 (FastAPI, Jinja2, htmx, vanilla JS), on branch `feat/web-step1`.

**Spec:** `docs/superpowers/specs/2026-09-26-manhwatok-web-design.md` — "Art picker", "Picks editor (… and Edit picks)". The user asked on 2026-09-26 to change a title's picture "like from pin" and "anything, like the panel style"; they chose every group: art style, picks, texts, look.

## Global Constraints

- Everything from steps 1–2 holds (127.0.0.1, Host/Origin guard, notices as HTTP 200 + `HX-Trigger` with `HX-Reswap: none`, `pytest.importorskip("fastapi")`, 100 columns, commit trailer).
- Chapter posts draw their own panels: art, art style, cover style and picks are refused for them with the TUI's words (`post X is a chapter post — it draws its own panels` / `… has no picks to edit`); texts are allowed.
- A change is refused while a render runs (`still rendering — try again when it's done`, level warning) — the renderer reads the post once at its start.
- Picture sources: `covers`, `fanart`, `pins`, `reddit` (`ArtSourceName`); orders `relevance`, `size`, `portrait`, `popular` (`ArtOrder`); a tag is refused with `covers` (the CLI's words: `a tag narrows fanart, pins or reddit; covers has no such vocabulary`).
- Own pictures: `.jpg .jpeg .png .webp .gif`, at most 20 MB uploaded.
- Copy: sentence case; a button says what happens; a finished job's toast says what happened.

## Review Focus

- A source that fails (Pinterest without gallery-dl, Reddit without credentials, a network error) → the picker shows that message in place of the pictures; nothing else breaks (Task 4).
- Choosing a picture after the server restarted (the list is gone) → "this list is gone — find pictures again", nothing changed (Task 4).
- Editing picks keeps each kept title's own picture and scenes (custom art survives a reorder) (Task 3).
- An upload that isn't a picture, is empty, or too big → a notice, the title's art untouched (Task 5).
- The same edit submitted twice (double click) → at most one render job; the second is refused as busy, not run twice (Tasks 2–5, by the lane).

---

## File Structure

```
src/manhwatok/app/edit_post.py                 MOD  update_post_texts()
src/manhwatok/web/drafts.py                     MOD  ArtList, ArtLists
src/manhwatok/web/routes/edit.py                NEW  the Edit page and every change route
src/manhwatok/web/server.py                     MOD  app.state.art_lists, include edit.router
src/manhwatok/web/templates/edit.html           NEW  the page: texts & look, picks, art
src/manhwatok/web/templates/_edit_art_titles.html NEW  one card per pick with its current picture
src/manhwatok/web/templates/_art_picker.html    NEW  source/order/tag form + the options grid + own picture
src/manhwatok/web/templates/_post_detail.html   MOD  an "Edit" button
src/manhwatok/web/static/app.css                MOD  edit page styles
tests/unit/test_edit_post.py                    MOD  update_post_texts tests (file exists? else NEW)
tests/web/test_edit.py                          NEW
README.md                                       MOD
```

---

### Task 1: `update_post_texts` in the app layer

**Files:**
- Modify: `src/manhwatok/app/edit_post.py`
- Test: `tests/unit/test_edit_texts.py` (new file)

**Interfaces:**
- Produces: `TEXT_FIELDS = ("title", "hashtags", "emojis", "byline", "cta_title", "cta_follow", "accent")`; `update_post_texts(post_id: str, changes: dict[str, str], tools: PostTools) -> ListPost` — saves the given fields (stripped); title must not be blank (`DraftError("give the post a title")`); accent through `check_accent` (raises `InvalidName`); a blank `cta_title` / `cta_follow` goes back to `DEFAULT_CTA_TITLE` / `DEFAULT_CTA_FOLLOW`; unknown field names raise `ValueError`. Does not render.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_edit_texts.py`:
```python
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
    assert (again.cta_title, again.cta_follow, again.accent) == ("Read *which*?", "Follow!", "#ff5588")


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
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_edit_texts.py -q`
Expected: FAIL — `ImportError: cannot import name 'update_post_texts'`.

- [ ] **Step 3: Write it**

Add to `src/manhwatok/app/edit_post.py` (imports: `from manhwatok.domain.color import check_accent`, `from manhwatok.domain.post import DEFAULT_CTA_FOLLOW, DEFAULT_CTA_TITLE, ListPost` — add only what isn't imported yet):
```python
TEXT_FIELDS = ("title", "hashtags", "emojis", "byline", "cta_title", "cta_follow", "accent")
_DEFAULT_TEXTS = {"cta_title": DEFAULT_CTA_TITLE, "cta_follow": DEFAULT_CTA_FOLLOW}


def update_post_texts(post_id: str, changes: dict[str, str], tools: PostTools) -> ListPost:
    """Save a post's words and accent — only the fields given, stripped. A blank end-slide text
    goes back to its default; a blank title is refused. Doesn't render: the caller does."""
    unknown = set(changes) - set(TEXT_FIELDS)
    if unknown:
        raise ValueError(f"not a post text: {', '.join(sorted(unknown))}")
    update: dict[str, str] = {}
    for name, value in changes.items():
        value = value.strip()
        if name == "title" and not value:
            raise DraftError("give the post a title")
        if name == "accent":
            value = check_accent(value)
        if name in _DEFAULT_TEXTS and not value:
            value = _DEFAULT_TEXTS[name]
        update[name] = value
    post = tools.posts.get(post_id).model_copy(update=update)
    tools.posts.save(post)
    return post
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_edit_texts.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/manhwatok/app/edit_post.py tests/unit/test_edit_texts.py
git commit -m "feat: update_post_texts — change a post's words and accent"
```

---

### Task 2: The Edit page and "Texts and look"

**Files:**
- Create: `src/manhwatok/web/routes/edit.py`, `templates/edit.html`
- Modify: `server.py` (include `edit.router`), `templates/_post_detail.html` (Edit button), `static/app.css`
- Test: `tests/web/test_edit.py`

**Interfaces:**
- Consumes: `update_post_texts`, `TEXT_FIELDS` (Task 1); `restyle(post_id, art, tools)`, `set_cover(post_id, style, tools)`, `render_post` (`manhwatok.app.render_post`); `RENDER`, `Busy`; `done`, `page`, `ctx_of`; `STILL_RENDERING` from `routes/posts.py`.
- Produces:
  - `start_change(request, post_id, heading, change: Callable[[PostTools], str | None] | None, render: bool = True) -> Response` in `routes/edit.py`: runs `change(tools)` then (unless `render=False`) `render_post` in the render lane as one job; the job logs `post <id> · <n> slides` and publishes `changed posts`; its outcome is `"<what change returned, or heading> — rendered post <id>"`; a busy lane → warning notice.
  - `GET /posts/{id}/edit` (page `"posts"`; 404-ish "gone" page when the post isn't there), sections with ids `#texts`, `#picks-section`, `#art-section`.
  - `POST /posts/{id}/settings` (form: the `TEXT_FIELDS`, `art`, `cover`) → saves texts, then art style and cover when they changed (refused for chapter posts), then renders.
  - The detail pane's `<a class="button" href="/posts/{id}/edit">Edit</a>`.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_edit.py`:
```python
import json
import threading

import pytest

pytest.importorskip("fastapi")

from manhwatok.app.render_post import render_post  # noqa: E402
from manhwatok.web.jobs import RENDER  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import chapter_post, post  # noqa: E402
from tests.web.helpers import client_for, wait_job  # noqa: E402

PID, CHAPTER = "20260914-0002", "20260915-0003"


def _ctx(tmp_path, **kwargs):
    ctx = make_ctx(tmp_path, **kwargs)
    ctx.tools.posts.save(post(id=PID))
    render_post(PID, ctx.tools)
    ctx.tools.posts.save(chapter_post(id=CHAPTER))
    return ctx


def _notice(response):
    return json.loads(response.headers["HX-Trigger"])["notice"]


def _last_job(client):
    return wait_job(client, client.app.state.jobs.recent()[0].id)


def test_the_detail_links_to_the_edit_page(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        assert f'href="/posts/{PID}/edit"' in client.get(f"/posts/{PID}").text


def test_the_edit_page_shows_the_posts_texts_and_look(tmp_path):
    ctx = _ctx(tmp_path)
    p = ctx.tools.posts.get(PID)
    with client_for(ctx) as client:
        html = client.get(f"/posts/{PID}/edit").text
    assert 'id="texts"' in html and 'id="picks-section"' in html and 'id="art-section"' in html
    assert f'name="title" value="{p.title}"' in html
    assert f'name="hashtags" value="{p.hashtags}"' in html
    assert f'name="accent" value="{p.accent}"' in html
    assert '<option value="background"' in html and '<option value="hero"' in html


def test_a_chapter_post_edits_its_texts_only(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        html = client.get(f"/posts/{CHAPTER}/edit").text
    assert 'id="texts"' in html
    assert 'id="art-section"' not in html and 'id="picks-section"' not in html
    assert "draws its own panels" in html


def test_an_unknown_post_says_it_is_gone(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        response = client.get("/posts/20260101-0000/edit")
    assert response.status_code == 200 and "is gone" in response.text


def test_saving_texts_and_look_saves_then_renders(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/settings", data={
            "title": "Fresh *title*", "hashtags": "#x", "emojis": "🔥", "byline": "",
            "cta_title": "Which one?", "cta_follow": "Follow", "accent": "#ff5588",
            "art": "background", "cover": "hero",
        })
        job = _last_job(client)
    saved = ctx.tools.posts.get(PID)
    assert (saved.title, saved.accent, saved.art.value, saved.cover.value) == (
        "Fresh *title*", "#ff5588", "background", "hero")
    assert _notice(response) == {"text": f"saving post {PID}…", "level": "info"}
    assert job.outcome == f"saved texts and look — rendered post {PID}" and not job.failed


def test_bad_texts_are_refused_before_anything_changes(tmp_path):
    ctx = _ctx(tmp_path)
    before = ctx.tools.posts.get(PID)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/settings", data={"title": "T", "accent": "blue"})
    assert _notice(response)["level"] == "error" and "accent" in _notice(response)["text"]
    assert ctx.tools.posts.get(PID) == before
    assert client.app.state.jobs.recent() == []


def test_a_chapter_posts_art_style_is_refused(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{CHAPTER}/settings", data={"title": "T", "art": "quad"})
    assert "draws its own panels" in _notice(response)["text"]


def test_changes_wait_for_a_running_render(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        release = threading.Event()
        job = client.app.state.jobs.start(
            RENDER, "render post a", lambda io: release.wait(5) and "ok"
        )
        response = client.post(f"/posts/{PID}/settings", data={"title": "Changed"})
        release.set()
        wait_job(client, job.id)
    assert _notice(response)["level"] == "warning"
    assert ctx.tools.posts.get(PID).title != "Changed"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_edit.py -q`
Expected: FAIL (404s, no Edit link).

- [ ] **Step 3: The routes**

`src/manhwatok/web/routes/edit.py`:
```python
"""Edit a post: its texts and look, its picks, and each title's picture. Every change goes
through the same app functions as the TUI and the CLI, then re-renders the post in the render
lane — one job per change, refused while another render runs."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.app.edit_post import TEXT_FIELDS, update_post_texts
from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_post, restyle, set_cover
from manhwatok.domain.errors import ManhwatokError, PostNotFound
from manhwatok.domain.models import ArtOrder, ArtSourceName, ArtStyle, CoverStyle
from manhwatok.domain.post import ListPost
from manhwatok.web.jobs import RENDER, Busy
from manhwatok.web.routes.common import ctx_of, done, page
from manhwatok.web.routes.posts import STILL_RENDERING

router = APIRouter()

Change = Callable[[PostTools], "str | None"]


def chapter_refusal(post: ListPost) -> str:
    return f"post {post.id} is a chapter post — it draws its own panels"


def start_change(
    request: Request, post_id: str, heading: str, change: Change | None, render: bool = True
) -> Response:
    """Run `change(tools)` and then render the post, as one job in the render lane."""
    ctx, bus = ctx_of(request), request.app.state.bus

    def work(io) -> str:
        tools = replace(ctx.tools, progress=io.progress)
        said = change(tools) if change is not None else None
        if render:
            slides = render_post(post_id, tools)
            io.progress(f"post {post_id} · {len(slides)} slides")
        bus.publish("changed", what="posts")
        return f"{said or heading} — rendered post {post_id}"

    try:
        request.app.state.jobs.start(RENDER, f"{heading} ({post_id})", work)
    except Busy as e:
        return done(request, str(e), "warning")
    return done(request, f"{_doing(heading)} post {post_id}…")


def _doing(heading: str) -> str:
    """"saved texts and look" → "saving" — the word the toast starts with while it runs."""
    verbs = {"saved": "saving", "changed": "changing", "filled": "filling", "cleared": "clearing"}
    first = heading.split()[0]
    return verbs.get(first, "updating")


def _rendering(request: Request) -> bool:
    return request.app.state.jobs.busy(RENDER) is not None


@router.get("/posts/{post_id}/edit", response_class=HTMLResponse)
def edit_page(request: Request, post_id: str) -> HTMLResponse:
    ctx = ctx_of(request)
    try:
        post = ctx.tools.posts.get(post_id)
    except PostNotFound:
        return page(request, "_post_gone.html", post_id=post_id, why="")
    return page(
        request,
        "edit.html",
        page="posts",
        post=post,
        chapter=chapter_refusal(post) if post.chapter else "",
        arts=list(ArtStyle),
        covers=list(CoverStyle),
        sources=list(ArtSourceName),
        orders=list(ArtOrder),
    )


@router.post("/posts/{post_id}/settings")
async def save_settings(request: Request, post_id: str) -> Response:
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    form = await request.form()
    ctx = ctx_of(request)
    try:
        post = ctx.tools.posts.get(post_id)
        texts = {name: str(form[name]) for name in TEXT_FIELDS if name in form}
        art = ArtStyle(str(form["art"])) if form.get("art") else post.art
        cover = CoverStyle(str(form["cover"])) if form.get("cover") else post.cover
        if post.chapter and (art is not post.art or cover is not post.cover):
            raise ManhwatokError(chapter_refusal(post))
        update_post_texts(post_id, texts, ctx.tools)
        if art is not post.art:
            restyle(post_id, art, ctx.tools)
        if cover is not post.cover:
            set_cover(post_id, cover, ctx.tools)
    except (ManhwatokError, ValueError, KeyError) as e:
        return done(request, str(e), "error")
    return start_change(request, post_id, "saved texts and look", None)
```
The toast while the job runs is `<doing> post <id>…` (the test expects `saving post <id>…` for "saved texts and look").

In `server.py`: include `edit.router` (`from manhwatok.web.routes import edit, files, header, new, posts`) — **before** `posts.router`, so `/posts/{id}/edit` isn't taken by `/posts/{post_id}`'s GET (`/posts/{id}/edit` has two segments, so there's no clash; order is still clearer).

- [ ] **Step 4: The page**

`templates/edit.html`:
```html
{% extends "base.html" %}
{% block title %}Edit {{ post.id }} · manhwatok{% endblock %}
{% block content %}
<div class="toolbar">
  <h1>Edit post</h1>
  <span class="muted">{{ post.title | plain }} · {{ post.id }}</span>
  <span class="spacer"></span>
  <a class="button" href="/posts?post={{ post.id }}">Back to the post</a>
</div>

<section id="texts" class="panel edit-section">
  <h2>Texts and look</h2>
  <form class="edit-grid" hx-post="/posts/{{ post.id }}/settings" hx-swap="none"
        hx-disabled-elt="find button.primary">
    <label class="field wide">Title <input name="title" value="{{ post.title }}" required></label>
    <label class="field">Hashtags <input name="hashtags" value="{{ post.hashtags }}"></label>
    <label class="field">Emojis <input name="emojis" value="{{ post.emojis }}" placeholder="none, or auto"></label>
    <label class="field">Byline <input name="byline" value="{{ post.byline }}" placeholder="@{{ post.account or 'handle' }}"></label>
    <label class="field">Accent
      <span class="accent-pick"><input type="color" value="{{ post.accent }}" data-mirror="accent" aria-label="Pick the accent">
        <input name="accent" value="{{ post.accent }}"></span></label>
    <label class="field">End slide title <input name="cta_title" value="{{ post.cta_title }}"></label>
    <label class="field">End slide follow line <input name="cta_follow" value="{{ post.cta_follow }}"></label>
    {% if not chapter %}
    <label class="field">Art style
      <select name="art">{% for a in arts %}<option value="{{ a.value }}" {% if a == post.art %}selected{% endif %}>{{ a.value }}</option>{% endfor %}</select>
    </label>
    <label class="field">Cover
      <select name="cover">{% for c in covers %}<option value="{{ c.value }}" {% if c == post.cover %}selected{% endif %}>{{ c.value }}</option>{% endfor %}</select>
    </label>
    {% endif %}
    <div class="wide actions"><button class="button primary">Save and render</button></div>
  </form>
</section>

{% if chapter %}
<p class="empty">{{ chapter }}: its picks and pictures can't be changed here.</p>
{% else %}
<section id="picks-section" class="panel edit-section">
  <h2>Picks</h2>
  <div hx-get="/posts/{{ post.id }}/picks" hx-trigger="load" hx-swap="outerHTML"></div>
</section>

<section id="art-section" class="panel edit-section">
  <h2>Pictures</h2>
  <div id="art-titles" hx-get="/posts/{{ post.id }}/art" hx-trigger="load, changed-posts from:body"></div>
  <div id="art-panel"></div>
</section>
{% endif %}
{% endblock %}
```
(The `/picks` and `/art` fragments come in Tasks 3–4; until then those loads 404 harmlessly.)

In `_post_detail.html`, in `.actions`, right after the Render button:
```html
    <a class="button" href="/posts/{{ d.post.id }}/edit">Edit</a>
```

Append to `static/app.css`:
```css
/* edit */
.edit-section { margin-bottom: 20px; }
.edit-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.edit-grid .wide { grid-column: 1 / -1; }
.accent-pick { display: flex; gap: 8px; }
.accent-pick input[type="color"] { width: 44px; padding: 2px; height: 38px; }
.accent-pick input[name="accent"] { flex: 1; }
.art-titles { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 14px; }
.art-title { text-align: left; }
.art-title .thumb { aspect-ratio: 2 / 3; border-radius: var(--radius-card); overflow: hidden; background: var(--gutter); }
.art-title img { width: 100%; height: 100%; object-fit: cover; display: block; }
.art-title .name { font-weight: 700; font-size: 13px; margin: 6px 0; }
.art-title .own { font-size: 12px; color: var(--accent); }
.art-picker { margin-top: 18px; border-top: 1px solid var(--line); padding-top: 16px; }
.art-options { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; margin-top: 12px; }
.art-option { all: unset; cursor: pointer; display: block; }
.art-option .thumb { aspect-ratio: 3 / 4; border-radius: 8px; overflow: hidden; background: var(--gutter); outline: 2px solid transparent; outline-offset: 2px; }
.art-option img { width: 100%; height: 100%; object-fit: cover; display: block; }
.art-option:hover .thumb, .art-option:focus-visible .thumb { outline-color: var(--accent); }
.art-option .meta { font-size: 12px; color: var(--muted); margin-top: 4px; }
.art-error { color: var(--danger); }
```

And in `static/app.js` (inside the IIFE), keep the accent colour well and text field in step:
```js
  // Edit: the colour well and the accent field say the same thing.
  document.addEventListener("input", (e) => {
    const name = e.target.dataset?.mirror;
    if (name) e.target.closest("form").querySelector(`input[name="${name}"]`).value = e.target.value;
    if (e.target.name === "accent" && /^#[0-9a-fA-F]{6}$/.test(e.target.value)) {
      const well = e.target.closest("form").querySelector('[data-mirror="accent"]');
      if (well) well.value = e.target.value.toLowerCase();
    }
  });
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/web -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/manhwatok/web tests/web/test_edit.py
git commit -m "feat(web): an Edit page — change a post's texts and look, then re-render"
```

---

### Task 3: Edit the picks of an existing post

**Files:**
- Modify: `routes/edit.py`, `templates/_new_results.html` (split the picks editor out), create `templates/_picks_editor.html`
- Test: `tests/web/test_edit.py`

**Interfaces:**
- Consumes: `update_picks(post_id, title, items, tools) -> list[Path]` (`manhwatok.app.edit_post`; it saves and renders itself), `first_sentence`, `chapter_label`, `MAX_ITEMS`, step 2's picks JS (it works on `#picks-form`, `#candidates[data-max]`, `.candidate[data-id][aria-pressed]` with a `<template>`, `#picks .pick[data-id]`, `hook-<id>` inputs).
- Produces: `templates/_picks_editor.html` — the candidates grid and the picks list, used by both New post and Edit (context: `candidates`, `picks` (list of `PostItem`), `picked` (set of ids), `label`, `hook`, `max_items`); `GET /posts/{id}/picks` → `<form id="picks-form" hx-post="/posts/{id}/picks">` with the editor and a hidden `title`; `POST /posts/{id}/picks` (repeated `pick`, `hook-<id>`, `title`) → `update_picks` in the render lane, keeping each kept title's `PostItem` (its `custom_art` and `scenes`) and only changing its hook.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_edit.py`:
```python
from tests.unit.fakes import manhwa  # noqa: E402


def _picky(tmp_path):
    """PID with three candidates: 1 and 2 picked (1 with its own picture), 3 not."""
    from manhwatok.domain.post import PostItem

    ctx = _ctx(tmp_path)
    cands = [manhwa(anilist_id=n, title=f"Title {n}", description=f"Hook {n}. More.") for n in (1, 2, 3)]
    items = [PostItem(manhwa=cands[0], hook="one", custom_art="art-1.jpg"),
             PostItem(manhwa=cands[1], hook="two")]
    ctx.tools.posts.save(ctx.tools.posts.get(PID).model_copy(update={"candidates": cands, "items": items}))
    (ctx.tools.posts.folder(PID) / "art-1.jpg").write_bytes(b"jpg")
    return ctx


def test_the_picks_editor_shows_the_posts_picks_and_its_other_candidates(tmp_path):
    with client_for(_picky(tmp_path)) as client:
        html = client.get(f"/posts/{PID}/picks").text
    assert f'hx-post="/posts/{PID}/picks"' in html and 'id="picks-form"' in html
    assert html.count('aria-pressed="true"') == 2 and html.count('aria-pressed="false"') == 1
    assert 'name="hook-1" value="one"' in html
    assert 'name="hook-3" value="Hook 3."' in html  # ready in its template


def test_editing_picks_keeps_each_kept_titles_picture(tmp_path):
    ctx = _picky(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/picks", data={
            "title": "T", "pick": ["3", "1"], "hook-3": "three", "hook-1": "first now",
        })
        job = _last_job(client)
    items = ctx.tools.posts.get(PID).items
    assert [(i.manhwa.anilist_id, i.hook, i.custom_art) for i in items] == [
        (3, "three", ""), (1, "first now", "art-1.jpg")]
    assert _notice(response)["text"] == f"saving post {PID}…"
    assert job.outcome == f"saved the picks — rendered post {PID}"


def test_a_pick_that_is_not_a_candidate_is_refused(tmp_path):
    ctx = _picky(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/picks", data={"title": "T", "pick": ["99"]})
    assert _notice(response)["level"] == "error"
    assert [i.manhwa.anilist_id for i in ctx.tools.posts.get(PID).items] == [1, 2]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_edit.py -q`
Expected: the three new tests FAIL.

- [ ] **Step 3: One picks editor for both pages**

Create `templates/_picks_editor.html` by moving, from `_new_results.html`, the `<section>` holding `#candidates` (loop over `candidates` instead of `draft.candidates`) and the `<h3>Picks, in order</h3>` + `<ol class="picks" id="picks">…</ol>` block — unchanged otherwise. In `_new_results.html`, replace them with `{% include "_picks_editor.html" %}` placed so the layout stays the same: the candidates `<section>` first, then the panel `<section>` with Title, `{% include "_picks_list.html" %}`… To keep it simple and identical: split into two includes, `_picks_candidates.html` (the candidates section) and `_picks_list.html` (the `h3` + `ol`), and include each where its block was. In `routes/new.py`'s search, pass `candidates=results` to the template alongside `draft` (the includes read `candidates`).

- [ ] **Step 4: The routes and the fragment**

Append to `routes/edit.py` (imports: `from fastapi.responses import HTMLResponse`, `from manhwatok.app.edit_post import update_picks`, `from manhwatok.domain.labels import chapter_label`, `from manhwatok.domain.post import MAX_ITEMS, PostItem`, `from manhwatok.domain.text import first_sentence`, `from manhwatok.domain.errors import DraftError`):
```python
@router.get("/posts/{post_id}/picks", response_class=HTMLResponse)
def picks_editor(request: Request, post_id: str) -> HTMLResponse:
    post = ctx_of(request).tools.posts.get(post_id)
    return page(
        request,
        "_edit_picks.html",
        post=post,
        candidates=post.candidates,
        picks=post.items,
        picked={i.manhwa.anilist_id for i in post.items},
        label=chapter_label,
        hook=first_sentence,
        max_items=MAX_ITEMS,
    )


@router.post("/posts/{post_id}/picks")
async def save_picks(request: Request, post_id: str) -> Response:
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    form = await request.form()
    ctx = ctx_of(request)
    try:
        post = ctx.tools.posts.get(post_id)
        if post.chapter:
            raise ManhwatokError(f"post {post_id} is a chapter post — it has no picks to edit")
        kept = {str(i.manhwa.anilist_id): i for i in post.items}
        by_id = {str(m.anilist_id): m for m in post.candidates}
        items = []
        for pid in (str(p) for p in form.getlist("pick")):
            if pid not in by_id:
                raise DraftError(f"title {pid} is not one of this post's candidates")
            hook = str(form.get(f"hook-{pid}", "")).strip()
            items.append(
                kept[pid].model_copy(update={"hook": hook}) if pid in kept
                else PostItem(manhwa=by_id[pid], hook=hook)
            )
        title = str(form.get("title", post.title))
    except ManhwatokError as e:
        return done(request, str(e), "error")

    def change(tools) -> str:
        update_picks(post_id, title, items, tools)  # checks the picks, saves, renders
        return "saved the picks"

    return start_change(request, post_id, "saved the picks", change, render=False)
```
`start_change` with `render=False` still logs nothing about slides; make it log them when `render` is False too by having `change` return the text and letting `update_picks`'s own render stand. (The test only checks the outcome text.) Note `update_picks` raises `DraftError` for a blank title / no picks / duplicates inside the job — the job then ends with that error, which the toast shows.

`templates/_edit_picks.html`:
```html
<form id="picks-form" class="new" hx-post="/posts/{{ post.id }}/picks" hx-swap="none"
      hx-disabled-elt="find button.primary">
  <input type="hidden" name="title" value="{{ post.title }}">
  {% include "_picks_candidates.html" %}
  <section class="panel">
    {% include "_picks_list.html" %}
    <div class="actions"><button class="button primary">Save picks and render</button></div>
  </section>
</form>
```
The picks JS calls `ranks()` after an `htmx:afterSwap` into `#results`; also call it after any swap that brings a `#picks-form` — change that listener to:
```js
  document.body.addEventListener("htmx:afterSwap", () => { if (document.getElementById("picks")) ranks(); });
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/web -q`
Expected: all PASS (New post tests included — the split templates render the same markup).

- [ ] **Step 6: Commit**

```bash
git add src/manhwatok/web tests/web/test_edit.py
git commit -m "feat(web): edit an existing post's picks, each kept title keeping its picture"
```

---

### Task 4: Pictures — list a source's options for a title and use one

**Files:**
- Modify: `drafts.py` (`ArtList`, `ArtLists`), `server.py` (`app.state.art_lists`), `routes/edit.py`
- Create: `templates/_edit_art_titles.html`, `templates/_art_picker.html`
- Test: `tests/web/test_edit.py`

**Interfaces:**
- Consumes: `list_art(post_id, anilist_id, tools, source, tag=None, order=ArtOrder.RELEVANCE) -> list[ArtOption]` and `use_art(post_id, anilist_id, option, tools, source) -> Path` (`manhwatok.app.art_options`); `ctx.art_sources: dict[ArtSourceName, ArtSource]`; `ArtOption(label, url, width, height, likes)` (`manhwatok.ports.art`); `file_url` (`routes/files.py`).
- Produces:
  - `drafts.ArtList` (`id`, `post_id`, `anilist_id`, `source: ArtSourceName`, `options: list[ArtOption]`), `drafts.ArtLists(keep=20)`: `add(post_id, anilist_id, source, options) -> ArtList`, `get(list_id) -> ArtList` (raises `ManhwatokError("this list is gone — find pictures again")`).
  - `GET /posts/{id}/art` → `_edit_art_titles.html`: one `.art-title` per pick with its current picture (`file_url` of the post folder's `custom_art`, else the AniList `cover_url`), "own picture" marked, and a `Change picture` button `hx-get="/posts/{id}/art/{aid}"` into `#art-panel`.
  - `GET /posts/{id}/art/{aid}?source=&order=&tag=` → `_art_picker.html` for that title: the source/order/tag form (`hx-get` to itself, into `#art-panel`), the options grid (each `<button class="art-option" hx-post="/posts/{id}/art/{aid}/use" hx-vals='{"list": "<id>", "index": <n>}'>`), or the source's error message (`.art-error`). With no `source` given it shows the form only.
  - `POST /posts/{id}/art/{aid}/use` (form `list`, `index`) → `use_art` then render, in one job.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_edit.py`:
```python
from manhwatok.ports.art import ArtOption  # noqa: E402
from tests.unit.fakes import FakeArtSource  # noqa: E402

OPTIONS = [
    ArtOption("small", "https://pins.test/a.jpg", 400, 600, likes=5),
    ArtOption("big", "https://pins.test/b.jpg", 1200, 1800, likes=50),
]


def _arty(tmp_path, pins=None):
    ctx = _ctx(tmp_path, pins=pins or FakeArtSource(options={1: OPTIONS}))
    first = ctx.tools.posts.get(PID).items[0].manhwa.anilist_id
    return ctx, first


def test_each_pick_shows_its_picture_and_a_way_to_change_it(tmp_path):
    ctx, first = _arty(tmp_path)
    with client_for(ctx) as client:
        html = client.get(f"/posts/{PID}/art").text
    assert html.count('class="art-title"') == len(ctx.tools.posts.get(PID).items)
    assert f'hx-get="/posts/{PID}/art/{first}"' in html


def test_a_source_lists_its_pictures_in_the_order_asked(tmp_path):
    ctx, first = _arty(tmp_path)
    with client_for(ctx) as client:
        html = client.get(f"/posts/{PID}/art/{first}", params={"source": "pins", "order": "popular"}).text
    assert html.index("https://pins.test/b.jpg") < html.index("https://pins.test/a.jpg")
    assert html.count('class="art-option"') == 2
    assert "1200×1800" in html and "50 likes" in html


def test_a_failing_source_says_why_in_the_picker(tmp_path):
    from manhwatok.domain.errors import ManhwatokError

    broken = FakeArtSource(error=ManhwatokError("pinterest art needs gallery-dl: uv sync --extra pinterest"))
    ctx, first = _arty(tmp_path, pins=broken)
    with client_for(ctx) as client:
        response = client.get(f"/posts/{PID}/art/{first}", params={"source": "pins"})
    assert response.status_code == 200
    assert 'class="art-error"' in response.text and "gallery-dl" in response.text


def test_a_tag_with_covers_is_refused(tmp_path):
    ctx, first = _arty(tmp_path)
    with client_for(ctx) as client:
        html = client.get(f"/posts/{PID}/art/{first}", params={"source": "covers", "tag": "x"}).text
    assert "covers has no such vocabulary" in html


def test_using_a_picture_downloads_it_as_the_titles_art_and_renders(tmp_path):
    ctx, first = _arty(tmp_path)
    pins = ctx.art_sources[__import__("manhwatok.domain.models", fromlist=["ArtSourceName"]).ArtSourceName.PINS]
    with client_for(ctx) as client:
        html = client.get(f"/posts/{PID}/art/{first}", params={"source": "pins"}).text
        list_id = html.split('"list": "')[1].split('"')[0]
        response = client.post(f"/posts/{PID}/art/{first}/use", data={"list": list_id, "index": "1"})
        job = _last_job(client)
    item = next(i for i in ctx.tools.posts.get(PID).items if i.manhwa.anilist_id == first)
    assert item.custom_art.startswith(f"art-{first}")
    assert pins.fetched == ["https://pins.test/b.jpg"]
    assert _notice(response)["text"] == f"changing post {PID}…"
    assert job.outcome == f"changed the picture of {item.manhwa.title} — rendered post {PID}"


def test_a_list_that_is_gone_asks_to_find_again(tmp_path):
    ctx, first = _arty(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/art/{first}/use", data={"list": "old", "index": "0"})
    assert _notice(response) == {"text": "this list is gone — find pictures again", "level": "error"}
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_edit.py -q`
Expected: the new tests FAIL.

- [ ] **Step 3: The lists store**

Append to `src/manhwatok/web/drafts.py`:
```python
@dataclass
class ArtList:
    id: str
    post_id: str
    anilist_id: int
    source: str  # an ArtSourceName value
    options: list  # list[ArtOption]


class ArtLists:
    """The pictures a source offered for one title, kept until one is chosen."""

    def __init__(self, keep: int = 20) -> None:
        self._keep = keep
        self._lock = threading.Lock()
        self._lists: OrderedDict[str, ArtList] = OrderedDict()

    def add(self, post_id: str, anilist_id: int, source: str, options: list) -> ArtList:
        found = ArtList(secrets.token_urlsafe(8), post_id, anilist_id, source, list(options))
        with self._lock:
            self._lists[found.id] = found
            while len(self._lists) > self._keep:
                self._lists.popitem(last=False)
        return found

    def get(self, list_id: str) -> ArtList:
        with self._lock:
            found = self._lists.get(list_id)
        if found is None:
            raise ManhwatokError("this list is gone — find pictures again")
        return found
```
In `server.py`: `app.state.art_lists = ArtLists()` (import it with `Drafts`).

- [ ] **Step 4: The routes**

Append to `routes/edit.py` (imports: `from manhwatok.app.art_options import list_art, use_art`, `from manhwatok.web.routes.files import file_url`):
```python
TAG_WITH_COVERS = "a tag narrows fanart, pins or reddit; covers has no such vocabulary"


def _picture(ctx, post: ListPost, item) -> str | None:
    """The title's picture as the slides draw it: its own art, else its AniList cover."""
    if item.custom_art:
        try:
            return file_url(ctx.tools.posts.folder(post.id) / item.custom_art)
        except OSError:
            pass
    return item.manhwa.cover_url


@router.get("/posts/{post_id}/art", response_class=HTMLResponse)
def art_titles(request: Request, post_id: str) -> HTMLResponse:
    ctx = ctx_of(request)
    post = ctx.tools.posts.get(post_id)
    titles = [(item, _picture(ctx, post, item)) for item in post.items]
    return page(request, "_edit_art_titles.html", post=post, titles=titles)


@router.get("/posts/{post_id}/art/{anilist_id}", response_class=HTMLResponse)
def art_picker(
    request: Request, post_id: str, anilist_id: int, source: str = "", order: str = "", tag: str = ""
) -> HTMLResponse:
    ctx = ctx_of(request)
    post = ctx.tools.posts.get(post_id)
    item = next((i for i in post.items if i.manhwa.anilist_id == anilist_id), None)
    context = dict(post=post, item=item, sources=list(ArtSourceName), orders=list(ArtOrder),
                   source=source, order=order or ArtOrder.RELEVANCE.value, tag=tag,
                   found=None, error="")
    if item is None:
        context["error"] = f"post {post_id} has no title {anilist_id}"
    elif source:
        try:
            chosen = ArtSourceName(source)
            if tag.strip() and chosen is ArtSourceName.COVERS:
                raise ManhwatokError(TAG_WITH_COVERS)
            options = list_art(post_id, anilist_id, ctx.tools, ctx.art_sources[chosen],
                               tag.strip() or None, ArtOrder(context["order"]))
            context["found"] = request.app.state.art_lists.add(post_id, anilist_id, source, options)
        except (ManhwatokError, ValueError) as e:
            context["error"] = str(e)
    return page(request, "_art_picker.html", **context)


@router.post("/posts/{post_id}/art/{anilist_id}/use")
async def use_picture(request: Request, post_id: str, anilist_id: int) -> Response:
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    form = await request.form()
    ctx = ctx_of(request)
    try:
        found = request.app.state.art_lists.get(str(form.get("list", "")))
        if (found.post_id, found.anilist_id) != (post_id, anilist_id):
            raise ManhwatokError("this list is for another title — find pictures again")
        option = found.options[int(str(form.get("index", "-1")))]
        source = ctx.art_sources[ArtSourceName(found.source)]
        name = next(i.manhwa.title for i in ctx.tools.posts.get(post_id).items
                    if i.manhwa.anilist_id == anilist_id)
    except (ManhwatokError, ValueError, IndexError, StopIteration) as e:
        text = str(e) if isinstance(e, ManhwatokError) else "that picture isn't in the list"
        return done(request, text, "error")

    def change(tools) -> str:
        use_art(post_id, anilist_id, option, tools, source)
        return f"changed the picture of {name}"

    return start_change(request, post_id, f"changed the picture of {name}", change)
```
`_doing("changed …")` → "changing" (test: `changing post <id>…`).

- [ ] **Step 5: The fragments**

`templates/_edit_art_titles.html`:
```html
<div class="art-titles">
  {% for item, picture in titles %}
  <div class="art-title">
    <div class="thumb">{% if picture %}<img src="{{ picture }}" alt="" loading="lazy" referrerpolicy="no-referrer">{% endif %}</div>
    <div class="name">{{ loop.index }}. {{ item.manhwa.title }}</div>
    {% if item.custom_art %}<div class="own">Own picture</div>{% endif %}
    <button type="button" class="button" hx-get="/posts/{{ post.id }}/art/{{ item.manhwa.anilist_id }}"
            hx-target="#art-panel">Change picture</button>
  </div>
  {% endfor %}
</div>
```
Each `.art-title` must render as exactly `<div class="art-title">` (the test counts that string).

`templates/_art_picker.html`:
```html
<div class="art-picker">
  <h3>{{ item.manhwa.title if item else "Picture" }}</h3>
  {% if item %}
  <form class="toolbar" hx-get="/posts/{{ post.id }}/art/{{ item.manhwa.anilist_id }}" hx-target="#art-panel"
        hx-indicator="#finding">
    <label class="field">Source
      <select name="source">{% for s in sources %}<option value="{{ s.value }}" {% if s.value == source %}selected{% endif %}>{{ s.value }}</option>{% endfor %}</select>
    </label>
    <label class="field">Order
      <select name="order">{% for o in orders %}<option value="{{ o.value }}" {% if o.value == order %}selected{% endif %}>{{ o.value }}</option>{% endfor %}</select>
    </label>
    <label class="field">Tag <input name="tag" value="{{ tag }}" placeholder="fanart, pins or reddit only"></label>
    <span id="finding" class="htmx-indicator muted">Looking…</span>
    <button class="button primary">Find pictures</button>
  </form>
  {% endif %}
  {% if error %}<p class="art-error">{{ error }}</p>{% endif %}
  {% if found is not none %}
    {% if found.options %}
    <div class="art-options">
      {% for o in found.options %}
      <button type="button" class="art-option" hx-post="/posts/{{ post.id }}/art/{{ item.manhwa.anilist_id }}/use"
              hx-vals='{"list": "{{ found.id }}", "index": {{ loop.index0 }}}' hx-swap="none"
              title="Use this picture">
        <div class="thumb"><img src="{{ o.url }}" alt="{{ o.label }}" loading="lazy" referrerpolicy="no-referrer"></div>
        <div class="meta">{{ o.label }}{% if o.width %} · {{ o.width }}×{{ o.height }}{% endif %}{% if o.likes %} · {{ o.likes }} likes{% endif %}</div>
      </button>
      {% endfor %}
    </div>
    {% else %}
    <p class="empty">{{ source }} has no pictures of this title. Try another source or tag.</p>
    {% endif %}
  {% endif %}
</div>
```
Each option must render as exactly `class="art-option"` (the test counts it). `found.id` is a `token_urlsafe` string (letters, digits, `-_`), safe inside the JSON.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/web -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/manhwatok/web tests/web/test_edit.py
git commit -m "feat(web): change a title's picture from covers, fanart, Pinterest or Reddit"
```

---

### Task 5: Own pictures, clearing, and filling every title from a source

**Files:**
- Modify: `routes/edit.py`, `templates/_art_picker.html`, `templates/edit.html`
- Test: `tests/web/test_edit.py`

**Interfaces:**
- Consumes: `set_item_art(post_id, anilist_id, source: Path, tools) -> Path`, `clear_item_art(post_id, anilist_id, tools)` (`manhwatok.app.item_art`); `looks_like_url(text) -> bool`, `download_picture(url, into: Path, client=None, timeout=20.0) -> Path` (`manhwatok.adapters.picture_download`); `render_from_source(post_id, tools, source, tag=None, order=None, pick=1, replace=False) -> tuple[int | None, list[Path]]` (`manhwatok.app.render_post`).
- Produces:
  - `POST /posts/{id}/art/{aid}/own` — multipart form with `url` (text) or `file` (upload, ≤ 20 MB, a picture suffix): the URL is downloaded inside the job; an upload is written to a temp folder first and moved in by `set_item_art` inside the job; then render.
  - `POST /posts/{id}/art/{aid}/clear` → `clear_item_art` then render.
  - `POST /posts/{id}/art/fill` (form `source`, `order`, `tag`, `replace`) → `render_from_source` in one job; outcome `filled <n> titles from <source> — rendered post <id>` (`<n>` = what it returned; for a quad post, `filled the scenes from <source>`).
  - The picker's "Your own picture" form and "Use the AniList cover" (clear) button; the Pictures section's "Fill every title" form.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_edit.py`:
```python
import io  # noqa: E402

from PIL import Image  # noqa: E402

from manhwatok.web.routes import edit as edit_routes  # noqa: E402


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 60), (200, 50, 50)).save(buffer, "PNG")
    return buffer.getvalue()


def _item(ctx, anilist_id):
    return next(i for i in ctx.tools.posts.get(PID).items if i.manhwa.anilist_id == anilist_id)


def test_an_uploaded_picture_becomes_the_titles_art(tmp_path):
    ctx, first = _arty(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/art/{first}/own",
                               files={"file": ("mine.png", _png(), "image/png")})
        job = _last_job(client)
    assert _item(ctx, first).custom_art == f"art-{first}.png"
    assert not job.failed and _notice(response)["level"] == "info"


@pytest.mark.parametrize(
    ("name", "data", "said"),
    [("notes.txt", b"hello", "picture"), ("empty.png", b"", "empty")],
)
def test_an_upload_that_isnt_a_picture_changes_nothing(tmp_path, name, data, said):
    ctx, first = _arty(tmp_path)
    before = _item(ctx, first).custom_art
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/art/{first}/own", files={"file": (name, data, "x/y")})
    assert _notice(response)["level"] == "error" and said in _notice(response)["text"]
    assert _item(ctx, first).custom_art == before


def test_a_picture_from_a_url_is_downloaded_in_the_job(tmp_path, monkeypatch):
    ctx, first = _arty(tmp_path)
    seen = []

    def fake_download(url, into, client=None, timeout=20.0):
        seen.append(url)
        into.mkdir(parents=True, exist_ok=True)
        path = into / "picture.png"
        path.write_bytes(_png())
        return path

    monkeypatch.setattr(edit_routes, "download_picture", fake_download)
    with client_for(ctx) as client:
        client.post(f"/posts/{PID}/art/{first}/own", data={"url": "https://i.pinimg.com/x.png"})
        job = _last_job(client)
    assert seen == ["https://i.pinimg.com/x.png"] and not job.failed
    assert _item(ctx, first).custom_art == f"art-{first}.png"


def test_neither_file_nor_url_says_so(tmp_path):
    ctx, first = _arty(tmp_path)
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/art/{first}/own", data={"url": "not a link"})
    assert _notice(response) == {"text": "give a picture file or an http(s) link", "level": "error"}


def test_clearing_goes_back_to_the_anilist_cover(tmp_path):
    ctx, first = _arty(tmp_path)
    with client_for(ctx) as client:
        client.post(f"/posts/{PID}/art/{first}/own", files={"file": ("m.png", _png(), "image/png")})
        _last_job(client)
        response = client.post(f"/posts/{PID}/art/{first}/clear")
        job = _last_job(client)
    assert _item(ctx, first).custom_art == ""
    assert job.outcome.startswith("cleared the picture of")
    assert _notice(response)["text"] == f"clearing post {PID}…"


def test_filling_every_title_from_a_source(tmp_path):
    options = {i: [ArtOption(f"p{i}", f"https://pins.test/{i}.jpg", 800, 1200)] for i in range(1, 40)}
    ctx, _ = _arty(tmp_path, pins=FakeArtSource(options=options))
    with client_for(ctx) as client:
        response = client.post(f"/posts/{PID}/art/fill", data={
            "source": "pins", "order": "portrait", "tag": "", "replace": "on"})
        job = _last_job(client)
    items = ctx.tools.posts.get(PID).items
    assert all(i.custom_art for i in items)
    assert job.outcome == f"filled {len(items)} titles from pins — rendered post {PID}"
    assert _notice(response)["text"] == f"filling post {PID}…"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_edit.py -q`
Expected: the new tests FAIL.

- [ ] **Step 3: The routes**

Append to `routes/edit.py` (imports: `import shutil, tempfile`, `from pathlib import Path`, `from fastapi import UploadFile`, `from manhwatok.adapters.picture_download import download_picture, looks_like_url`, `from manhwatok.app.item_art import clear_item_art, set_item_art`, `from manhwatok.app.render_post import render_from_source`):
```python
PICTURES = (".jpg", ".jpeg", ".png", ".webp", ".gif")
MAX_UPLOAD = 20 * 1024 * 1024


def _title_of(ctx, post_id: str, anilist_id: int) -> str:
    post = ctx.tools.posts.get(post_id)
    if post.chapter:
        raise ManhwatokError(chapter_refusal(post))
    for item in post.items:
        if item.manhwa.anilist_id == anilist_id:
            return item.manhwa.title
    raise ManhwatokError(f"post {post_id} has no title {anilist_id}")


@router.post("/posts/{post_id}/art/{anilist_id}/own")
async def own_picture(request: Request, post_id: str, anilist_id: int) -> Response:
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    form = await request.form()
    ctx = ctx_of(request)
    upload = form.get("file")
    url = str(form.get("url", "")).strip()
    try:
        name = _title_of(ctx, post_id, anilist_id)
        if isinstance(upload, UploadFile) and upload.filename:
            suffix = Path(upload.filename).suffix.lower()
            if suffix not in PICTURES:
                raise ManhwatokError(f"{upload.filename} isn't a picture ({', '.join(PICTURES)})")
            data = await upload.read(MAX_UPLOAD + 1)
            if not data:
                raise ManhwatokError(f"{upload.filename} is empty")
            if len(data) > MAX_UPLOAD:
                raise ManhwatokError(f"{upload.filename} is over 20 MB")
            folder = Path(tempfile.mkdtemp(prefix="manhwatok-upload-"))
            given = folder / f"upload{suffix}"
            given.write_bytes(data)
        elif looks_like_url(url):
            folder, given = Path(tempfile.mkdtemp(prefix="manhwatok-url-")), None
        else:
            raise ManhwatokError("give a picture file or an http(s) link")
    except ManhwatokError as e:
        return done(request, str(e), "error")

    def change(tools) -> str:
        try:
            picture = given or download_picture(url, folder)
            set_item_art(post_id, anilist_id, picture, tools)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        return f"changed the picture of {name}"

    return start_change(request, post_id, f"changed the picture of {name}", change)


@router.post("/posts/{post_id}/art/{anilist_id}/clear")
def clear_picture(request: Request, post_id: str, anilist_id: int) -> Response:
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    try:
        name = _title_of(ctx_of(request), post_id, anilist_id)
    except ManhwatokError as e:
        return done(request, str(e), "error")

    def change(tools) -> str:
        clear_item_art(post_id, anilist_id, tools)
        return f"cleared the picture of {name}"

    return start_change(request, post_id, f"cleared the picture of {name}", change)


@router.post("/posts/{post_id}/art/fill")
async def fill_pictures(request: Request, post_id: str) -> Response:
    if _rendering(request):
        return done(request, STILL_RENDERING, "warning")
    form = await request.form()
    ctx = ctx_of(request)
    try:
        post = ctx.tools.posts.get(post_id)
        if post.chapter:
            raise ManhwatokError(chapter_refusal(post))
        chosen = ArtSourceName(str(form.get("source", "")))
        tag = str(form.get("tag", "")).strip() or None
        if tag and chosen is ArtSourceName.COVERS:
            raise ManhwatokError(TAG_WITH_COVERS)
        order = ArtOrder(str(form.get("order") or ArtOrder.RELEVANCE.value))
        replace_all = bool(form.get("replace"))
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")
    bus = request.app.state.bus

    def work(io) -> str:
        tools = replace(ctx.tools, progress=io.progress)
        filled, slides = render_from_source(
            post_id, tools, ctx.art_sources[chosen], tag, order, replace=replace_all
        )
        io.progress(f"post {post_id} · {len(slides)} slides")
        bus.publish("changed", what="posts")
        what = f"filled the scenes from {chosen.value}" if filled is None else (
            f"filled {filled} titles from {chosen.value}")
        return f"{what} — rendered post {post_id}"

    try:
        request.app.state.jobs.start(RENDER, f"fill post {post_id}", work)
    except Busy as e:
        return done(request, str(e), "warning")
    return done(request, f"filling post {post_id}…")
```
If `render_from_source`'s return for the fake source doesn't count every title (it skips pictures it judges to hold text, or ones used twice), match the test to what it really returns and rule it in the ledger — the point is that every title gets art and the outcome says how many.

- [ ] **Step 4: The forms**

In `_art_picker.html`, after the `{% endif %}` that closes the options block and before the final `</div>`:
```html
  {% if item %}
  <form class="toolbar own-picture" hx-post="/posts/{{ post.id }}/art/{{ item.manhwa.anilist_id }}/own"
        hx-encoding="multipart/form-data" hx-swap="none" hx-disabled-elt="find button">
    <label class="field">Your own picture <input type="file" name="file" accept=".jpg,.jpeg,.png,.webp,.gif"></label>
    <label class="field">or a link <input name="url" placeholder="https://i.pinimg.com/…"></label>
    <button class="button">Use it</button>
  </form>
  {% if item.custom_art %}
  <button type="button" class="button" hx-post="/posts/{{ post.id }}/art/{{ item.manhwa.anilist_id }}/clear"
          hx-swap="none">Use the AniList cover again</button>
  {% endif %}
  {% endif %}
```
In `edit.html`, inside `#art-section` before `#art-titles`:
```html
  <form class="toolbar" hx-post="/posts/{{ post.id }}/art/fill" hx-swap="none" hx-disabled-elt="find button">
    <label class="field">Fill every title from
      <select name="source">{% for s in sources %}<option value="{{ s.value }}">{{ s.value }}</option>{% endfor %}</select>
    </label>
    <label class="field">Order
      <select name="order">{% for o in orders %}<option value="{{ o.value }}">{{ o.value }}</option>{% endfor %}</select>
    </label>
    <label class="field">Tag <input name="tag" placeholder="optional"></label>
    <label><input type="checkbox" name="replace"> Replace pictures already chosen</label>
    <button class="button">Fill and render</button>
  </form>
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/web -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/manhwatok/web tests/web/test_edit.py
git commit -m "feat(web): own pictures by file or link, back to the cover, fill every title"
```

---

### Task 6: Look at it, try it for real, document it

- [ ] **Step 1: Screenshots** — on port 8422 (8421 is the user's own server), headless Chrome 1440×900: the Edit page of a rendered list post (texts & look, picks, pictures), the picker after "Find pictures" from `covers` (MangaDex, real network), and after `pins` (real Pinterest via gallery-dl if installed, else its error message). Fix what's off (CSS-only fixes may skip tests; behaviour fixes get a test first).

- [ ] **Step 2: A real edit, end to end** — on a **copy** of one of the user's posts (create one: New post → search → save), in the browser: change its accent and emojis, drop a pick, change one title's picture from `covers`, upload an own picture for another, then delete the copy. Nothing of the user's own posts is changed.

- [ ] **Step 3: Docs and the full suite** — README "Web app": one paragraph on Edit (texts and look, picks, pictures from covers/fanart/Pinterest/Reddit/a file/a link, fill every title). Run `uv run pytest -q -m "not browser"`; all pass.

- [ ] **Step 4: Commit**

```bash
git add README.md src/manhwatok/web tests/web
git commit -m "docs: editing a post in the web app"
```
