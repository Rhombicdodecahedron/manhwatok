# Web app, step 2: the studio look and New post — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the web app its own dark "studio" look (posts as 9:16 cover cards, a big slide viewer) and let the user create a list post in the browser: search, pick and order titles with hooks, save, render, open it.

**Architecture:** Same FastAPI + Jinja2 + htmx app as step 1, on branch `feat/web-step1`. New post calls the TUI's own use cases: `suggest_for_account` (search), `prefill_items` (starting picks), `store_new_post` (save) and `render_post` in the render lane. A search's candidates live server-side in a small in-memory `Drafts` store between the search and the save; picking, ordering and hooks happen in the page and are posted back as an ordered list.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, htmx 2 (vendored), vanilla JS, CSS custom properties.

**Spec:** `docs/superpowers/specs/2026-09-26-manhwatok-web-design.md` — pages "Posts", "Picks editor", "Build" (list post). The user chose the "Dark studio" direction on 2026-09-26 and asked to be able to create a post. The art picker and the Chapter tab (also spec step 3) come in the next plan; they are not needed to create a post.

## Global Constraints

- Everything from step 1's plan still holds: 127.0.0.1 only, Host/Origin guard, no CDN at runtime for our own assets, expected failures as notices (HTTP 200 + `HX-Trigger`), `pytest.importorskip("fastapi")` in `tests/web`, 100-column lines, commit trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Typeface: Montserrat, the bundled `src/manhwatok/assets/fonts/Montserrat-Variable.ttf` (the slides' own font), served at `/fonts/Montserrat-Variable.ttf`.
- Palette (CSS custom properties on `:root`):
  `--gutter #1c1a24` (page), `--panel #25222f` (surfaces), `--raised #302c3c` (inputs, hover), `--line #3a3547`, `--paper #efe9dd` (text), `--muted #a59fb4`, `--accent` = the account's accent (default `#43c9e4`), status colours `--draft #a59fb4`, `--pending #f0b35c` (not rendered), `--ready #8fb3ff` (rendered), `--out #c69cf5` (exported), `--sent #7ccf8e`.
- Copy rules: sentence case, plain verbs, a button says what happens ("Save and render"), a toast says what happened, empty states say what to do.
- New post mirrors the TUI's Build rules exactly: a theme **or** tags/genres (not both, not neither); "How many" 1–50 (default 12); sort blank = score; min tag rank blank = 60 (theme's own when a theme is used); "Allow repeats" off; "Fill chapter counts" on; picks at most `MAX_ITEMS` (33); `check_picks` on save.

## Review Focus

- A search that AniList rejects or times out → an error notice in the page, the form kept as typed (Task 4).
- Saving after the server restarted (the search's candidates are gone) → "this search is gone — search again", nothing saved (Task 5).
- A save while another render runs → the post is saved and opened, and the notice says to render it when the other one is done (Task 5).
- Picks posted in an order different from the candidates' → the post's items follow the posted order, hooks attached to the right titles (Task 5).
- A candidate's text (title, description → hook) containing `<script>` or quotes → escaped everywhere, including the `value` of hook inputs (Task 4).

---

## File Structure

```
src/manhwatok/web/server.py            MOD  /fonts mount, drafts in app.state, include new router
src/manhwatok/web/drafts.py            NEW  Draft, Drafts (in-memory search results between search and save)
src/manhwatok/web/routes/new.py        NEW  GET /new, POST /new/search, POST /new/save
src/manhwatok/web/routes/posts.py      MOD  card thumbnails, account accent in the detail
src/manhwatok/web/templates/base.html          MOD  studio shell: sidebar nav (Posts, New post), mode switch at its foot
src/manhwatok/web/templates/_header.html       MOD  mode switch markup for the sidebar
src/manhwatok/web/templates/posts.html         MOD  toolbar + card grid + viewer
src/manhwatok/web/templates/_posts_table.html  MOD  the card grid (keeps its name and route)
src/manhwatok/web/templates/_post_detail.html  MOD  big slide viewer + filmstrip, sections
src/manhwatok/web/templates/new.html           NEW  the New post page
src/manhwatok/web/templates/_new_results.html  NEW  candidate cards + picks list + style + save
src/manhwatok/web/static/app.css       REWRITE the studio stylesheet
src/manhwatok/web/static/app.js        MOD  card selection, viewer, picks editor (pick, drag, move, remove)
tests/web/test_studio.py               NEW  shell, fonts, cards, viewer
tests/web/test_new.py                  NEW  New post search and save
tests/web/test_posts.py                MOD  markup expectations that change with the cards
README.md                              MOD  web app section
```

---

### Task 1: The studio shell — font, palette, sidebar

**Files:**
- Modify: `src/manhwatok/web/server.py`, `templates/base.html`, `templates/_header.html`
- Rewrite: `static/app.css`
- Test: `tests/web/test_studio.py`

**Interfaces:**
- Consumes: step 1's `page()`, `create_app()`.
- Produces: `/fonts/Montserrat-Variable.ttf`; the sidebar links `/posts` and `/new` (`aria-current="page"` from the template variable `page`: `"posts"` or `"new"`); the mode switch stays a `<form hx-post="/mode" hx-target="#header">` inside `<div id="header">` so step 1's `/mode` and `/busy` routes and tests keep working; CSS class vocabulary used by later tasks: `.toolbar`, `.button`, `.button.primary`, `.button.danger`, `.dot[data-status]`, `.status`, `.cards`, `.card`, `.viewer`, `.filmstrip`, `.panel`, `.field`, `.empty`.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_studio.py`:
```python
import pytest

pytest.importorskip("fastapi")

from tests.tui.helpers import make_ctx  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402


def test_the_slides_font_is_served_for_the_pages(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        response = client.get("/fonts/Montserrat-Variable.ttf")
    assert response.status_code == 200
    assert len(response.content) > 100_000


def test_the_shell_has_the_sidebar_and_the_mode_switch(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        html = client.get("/posts").text
    assert '<nav class="sidebar"' in html
    assert '<a href="/posts" aria-current="page"' in html
    assert '<a href="/new"' in html
    assert 'hx-post="/mode"' in html and 'id="header"' in html


def test_the_stylesheet_uses_the_font_and_the_palette(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        css = client.get("/static/app.css").text
    assert "Montserrat-Variable.ttf" in css
    for token in ("--gutter: #1c1a24", "--paper: #efe9dd", "--accent: #43c9e4"):
        assert token in css
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_studio.py -v`
Expected: FAIL — 404 on the font, no `/new` link, old tokens.

- [ ] **Step 3: Serve the font**

In `server.py`, next to the static mount:
```python
    # The slides' own font, so the pages and the slides read as one thing.
    fonts = Path(__file__).parent.parent / "assets" / "fonts"
    app.mount("/fonts", StaticFiles(directory=fonts), name="fonts")
```

- [ ] **Step 4: The shell**

`templates/base.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}manhwatok{% endblock %}</title>
  <link rel="stylesheet" href="/static/app.css">
  <script src="/static/htmx.min.js" defer></script>
  <script src="/static/app.js" defer></script>
</head>
<body>
  <nav class="sidebar" aria-label="Pages">
    <a class="brand" href="/">manhwatok</a>
    <a href="/posts" {% if page == "posts" %}aria-current="page"{% endif %}>Posts</a>
    <a href="/new" {% if page == "new" %}aria-current="page"{% endif %}>New post</a>
    <div id="header" class="sidebar-foot">{% include "_header.html" %}</div>
  </nav>
  <main class="main">{% block content %}{% endblock %}</main>
  <div id="toasts" aria-live="polite"></div>
  <dialog id="lightbox">
    <img alt="">
    <button type="button" class="prev" aria-label="Previous slide">‹</button>
    <button type="button" class="next" aria-label="Next slide">›</button>
    <button type="button" class="close" aria-label="Close">✕</button>
  </dialog>
</body>
</html>
```

`templates/_header.html`:
```html
<form class="mode" hx-post="/mode" hx-trigger="change" hx-target="#header">
  <label class="field">Upload via
    <select name="mode">
      {% for value, label in modes %}
      <option value="{{ value }}" {% if value == mode %}selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
  </label>
</form>
<div id="busy" hx-get="/busy" hx-trigger="job from:body">{% include "_busy.html" %}</div>
```

- [ ] **Step 5: The stylesheet**

Replace `static/app.css` entirely:
```css
@font-face {
  font-family: "Montserrat";
  src: url("/fonts/Montserrat-Variable.ttf") format("truetype");
  font-weight: 100 900;
  font-display: swap;
}
:root {
  --gutter: #1c1a24; --panel: #25222f; --raised: #302c3c; --line: #3a3547;
  --paper: #efe9dd; --muted: #a59fb4; --accent: #43c9e4;
  --draft: #a59fb4; --pending: #f0b35c; --ready: #8fb3ff; --out: #c69cf5; --sent: #7ccf8e;
  --danger: #ff7a6b;
  --radius-card: 10px; --radius-control: 999px;
  color-scheme: dark;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0; background: var(--gutter); color: var(--paper);
  font: 450 15px/1.5 "Montserrat", system-ui, sans-serif;
  display: grid; grid-template-columns: 200px minmax(0, 1fr);
}
a { color: inherit; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }

/* sidebar */
.sidebar {
  position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; gap: 2px;
  padding: 20px 12px; border-right: 1px solid var(--line);
}
.sidebar a { text-decoration: none; padding: 8px 12px; border-radius: 8px; color: var(--muted); font-weight: 600; }
.sidebar a:hover { color: var(--paper); background: var(--panel); }
.sidebar a[aria-current="page"] { color: var(--paper); background: var(--panel); box-shadow: inset 3px 0 0 var(--accent); }
.sidebar .brand { color: var(--paper); font-weight: 900; font-size: 19px; letter-spacing: -0.02em; margin-bottom: 18px; }
.sidebar-foot { margin-top: auto; display: flex; flex-direction: column; gap: 10px; font-size: 13px; }
.sidebar-foot .busy { color: var(--pending); }
.sidebar-foot .idle { color: var(--muted); }

.main { padding: 22px 28px; min-width: 0; }
h1 { font-size: 28px; font-weight: 800; letter-spacing: -0.02em; margin: 0 0 16px; }
h2 { font-size: 22px; font-weight: 800; letter-spacing: -0.01em; margin: 0 0 6px; line-height: 1.2; }
h3 { font-size: 14px; font-weight: 700; color: var(--muted); margin: 22px 0 8px; }
.muted { color: var(--muted); }

/* controls */
.field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--muted); }
input, select, textarea {
  font: inherit; color: var(--paper); background: var(--raised);
  border: 1px solid var(--line); border-radius: 8px; padding: 7px 10px;
}
input[type="checkbox"] { accent-color: var(--accent); }
.button, button {
  font: 600 14px/1 "Montserrat", sans-serif; color: var(--paper); background: var(--raised);
  border: 1px solid var(--line); border-radius: var(--radius-control); padding: 9px 16px; cursor: pointer;
}
.button:hover, button:hover { border-color: var(--muted); }
.button.primary { background: var(--accent); border-color: var(--accent); color: #0d0c12; }
.button.danger { color: var(--danger); }
.toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; margin-bottom: 16px; }
.toolbar .spacer { flex: 1; }

/* status */
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; background: var(--draft); }
.dot[data-status="draft"] { background: transparent; box-shadow: inset 0 0 0 2px var(--draft); }
.dot[data-status="not rendered"] { background: var(--pending); }
.dot[data-status="rendered"] { background: var(--ready); }
.dot[data-status="exported"] { background: var(--out); }
.dot[data-status="sent"] { background: var(--sent); }
.status { font-size: 12px; color: var(--muted); }

/* posts: cards + viewer */
.studio { display: grid; grid-template-columns: minmax(0, 1fr) minmax(420px, 44%); gap: 24px; align-items: start; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 16px; }
.card { position: relative; }
.card .open { all: unset; cursor: pointer; display: block; }
.card .thumb {
  aspect-ratio: 9 / 16; border-radius: var(--radius-card); overflow: hidden; background: var(--panel);
  outline: 2px solid transparent; outline-offset: 3px;
}
.card .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.card .thumb .none { display: grid; place-items: center; height: 100%; color: var(--muted); font-size: 13px; padding: 12px; text-align: center; }
.card.is-selected .thumb { outline-color: var(--accent); }
.card .title { font-weight: 700; font-size: 14px; line-height: 1.3; margin-top: 8px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card .meta { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); margin-top: 4px; }
.card .tick { position: absolute; top: 8px; left: 8px; background: rgba(28, 26, 36, .8); border-radius: 6px; padding: 3px 5px; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 18px; }
.viewer-pane { position: sticky; top: 22px; max-height: calc(100vh - 44px); overflow: auto; }
.viewer { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; }
.viewer .stage { aspect-ratio: 9 / 16; max-height: 62vh; margin: 0 auto; border-radius: var(--radius-card); overflow: hidden; background: var(--gutter); cursor: zoom-in; }
.viewer .stage img { height: 100%; width: 100%; object-fit: contain; display: block; }
.filmstrip { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; }
.filmstrip img { height: 86px; aspect-ratio: 9 / 16; object-fit: cover; border-radius: 6px; cursor: pointer; opacity: .55; }
.filmstrip img[aria-current="true"] { opacity: 1; outline: 2px solid var(--accent); }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0; align-items: center; }
.covers { display: flex; gap: 12px; }
.covers figure { margin: 0; text-align: center; font-size: 12px; color: var(--muted); cursor: pointer; }
.covers img { height: 150px; aspect-ratio: 9 / 16; object-fit: cover; border-radius: 8px; outline: 2px solid transparent; outline-offset: 2px; }
.covers .chosen img { outline-color: var(--accent); }
.caption { white-space: pre-wrap; background: var(--gutter); padding: 12px; border-radius: 8px; font-size: 14px; }
details > summary { cursor: pointer; font-weight: 700; color: var(--muted); margin: 16px 0 8px; }
.empty { color: var(--muted); padding: 40px 0; }

/* new post */
.new { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 38%); gap: 24px; align-items: start; }
.search { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; }
.search .wide { grid-column: 1 / -1; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
.candidate { position: relative; cursor: pointer; }
.candidate .thumb { aspect-ratio: 2 / 3; border-radius: var(--radius-card); overflow: hidden; background: var(--panel); }
.candidate img { width: 100%; height: 100%; object-fit: cover; display: block; }
.candidate .title { font-weight: 700; font-size: 14px; margin-top: 6px; line-height: 1.3; }
.candidate .meta { font-size: 12px; color: var(--muted); }
.candidate[aria-pressed="true"] .thumb { outline: 3px solid var(--accent); outline-offset: 2px; }
.candidate .rank { position: absolute; top: 8px; left: 8px; min-width: 26px; height: 26px; border-radius: 13px; background: var(--accent); color: #0d0c12; font-weight: 800; display: grid; place-items: center; padding: 0 6px; }
.candidate[aria-pressed="false"] .rank { display: none; }
.picks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; counter-reset: pick; }
.pick { display: grid; grid-template-columns: 28px 44px minmax(0, 1fr) auto; gap: 10px; align-items: start; background: var(--gutter); border: 1px solid var(--line); border-radius: 10px; padding: 8px; counter-increment: pick; }
.pick::before { content: counter(pick); font-weight: 800; color: var(--accent); align-self: center; text-align: center; }
.pick img { width: 44px; aspect-ratio: 2 / 3; object-fit: cover; border-radius: 4px; }
.pick .name { font-weight: 700; font-size: 14px; }
.pick input { width: 100%; margin-top: 4px; font-size: 13px; }
.pick .moves { display: flex; flex-direction: column; gap: 4px; }
.pick .moves button { padding: 4px 8px; font-size: 12px; }
.pick.dragging { opacity: .4; }
.style { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 14px; }

/* toasts, lightbox */
#toasts { position: fixed; right: 20px; bottom: 20px; display: flex; flex-direction: column; gap: 8px; z-index: 10; }
.toast { background: var(--raised); border: 1px solid var(--line); border-left: 4px solid var(--accent); padding: 10px 14px; border-radius: 10px; max-width: 440px; font-size: 14px; }
.toast.error { border-left-color: var(--danger); }
.toast.warning { border-left-color: var(--pending); }
#lightbox { border: 0; background: transparent; padding: 0; }
#lightbox::backdrop { background: rgba(12, 11, 16, .92); }
#lightbox img { max-height: 94vh; max-width: 94vw; display: block; border-radius: 8px; }
#lightbox button { position: fixed; top: 50%; background: rgba(0, 0, 0, .5); border: 0; font-size: 28px; }
#lightbox .prev { left: 20px; } #lightbox .next { right: 20px; } #lightbox .close { top: 20px; right: 20px; }

@media (max-width: 1100px) {
  .studio, .new { grid-template-columns: minmax(0, 1fr); }
  .viewer-pane { position: static; max-height: none; }
}
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/web -q`
Expected: all PASS (step 1's tests unaffected: the sidebar keeps `id="header"`, `/mode`, `/busy`).

- [ ] **Step 7: Commit**

```bash
git add src/manhwatok/web tests/web/test_studio.py
git commit -m "feat(web): the studio shell — the slides' font, a dark palette, a sidebar"
```

---

### Task 2: Posts as cover cards

**Files:**
- Modify: `src/manhwatok/web/routes/posts.py` (`_Row.thumb`), `templates/posts.html`, `templates/_posts_table.html`, `static/app.js`
- Modify: `tests/web/test_posts.py` (markup expectations)
- Test: `tests/web/test_studio.py`

**Interfaces:**
- Consumes: `file_url` (step 1), `rendered_files`.
- Produces: `_Row.thumb: str | None` (URL of the post's `01.png`, or None); each card is `<article class="card" data-post="{id}">` (plus ` is-selected`), with the tick `<input type="checkbox" name="ids" value="{id}">` (plus ` checked`), the opener `<button class="open" hx-get="/posts/{id}" hx-target="#detail" hx-push-url="/posts?post={id}">`, and `<span class="dot" data-status="{status}"></span><span class="status">{status}</span>`. `#posts-table` and `#bulk` keep their ids and refresh behaviour.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_studio.py`:
```python
from datetime import datetime, timezone  # noqa: E402

from manhwatok.app.render_post import render_post  # noqa: E402
from tests.unit.fakes import post  # noqa: E402

RENDERED, BARE = "20260914-0002", "20260913-0001"


def _two(ctx):
    ctx.tools.posts.save(post(id=BARE, created_at=datetime(2026, 9, 13, tzinfo=timezone.utc)))
    ctx.tools.posts.save(post(id=RENDERED, created_at=datetime(2026, 9, 14, tzinfo=timezone.utc)))
    render_post(RENDERED, ctx.tools)
    return ctx


def test_posts_are_cards_with_their_cover(tmp_path):
    with client_for(_two(make_ctx(tmp_path))) as client:
        html = client.get("/posts/table").text
    assert html.count('<article class="card') == 2
    assert f'<img src="/files/{RENDERED}/01.png?v=' in html
    assert "Not rendered yet" in html  # the bare post's card
    assert '<span class="dot" data-status="rendered"></span>' in html
    assert f'hx-get="/posts/{RENDERED}"' in html and 'hx-target="#detail"' in html


def test_the_selected_card_is_marked(tmp_path):
    with client_for(_two(make_ctx(tmp_path))) as client:
        html = client.get("/posts/table", params={"selected": BARE}).text
    assert html.count("is-selected") == 1
    card = html[html.index("is-selected"):]
    assert card.index(BARE) < card.index("</article>")
```
In `tests/web/test_posts.py`, change the selected-row test's last three lines to:
```python
    assert html.count("is-selected") == 1
    row = html[html.index("is-selected"):]
    assert row.index(DRAFT) < row.index("</article>")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_studio.py tests/web/test_posts.py -q`
Expected: the card tests and the changed selected-row test FAIL; the rest pass.

- [ ] **Step 3: The thumbnail**

In `routes/posts.py`, give `_Row` a thumbnail:
```python
@dataclass
class _Row:
    post: ListPost
    status: str
    planned: str  # in the post's account's time zone
    sent: str
    thumb: str | None = None  # the rendered cover (01.png), for the card
```
and in `_rows`, before `rows.append(...)`:
```python
        first = ctx.tools.posts.folder(post.id) / "01.png"
        thumb = file_url(first) if state not in ("draft", "not rendered") and first.is_file() else None
        rows.append(_Row(post, state, scheduled_text(post, zone), sent_text(post, zone), thumb))
```
(replacing the old `rows.append(_Row(post, state, scheduled_text(post, zone), sent_text(post, zone)))`). Keep lines under 100 columns (split the `thumb =` line if needed).

- [ ] **Step 4: The cards**

Replace `templates/_posts_table.html`:
```html
{% if rows %}
<form id="bulk">
  <div class="toolbar">
    <button type="button" class="button" hx-post="/posts/bulk" hx-include="#bulk" hx-vals='{"action": "render"}' hx-swap="none">Render ticked</button>
    <button type="button" class="button" hx-post="/posts/bulk" hx-include="#bulk" hx-vals='{"action": "export"}' hx-swap="none">Export ticked</button>
    <button type="button" class="button danger" hx-post="/posts/bulk" hx-include="#bulk" hx-vals='{"action": "delete"}' hx-swap="none"
      hx-confirm="Delete the ticked posts and their slides?">Delete ticked</button>
  </div>
  <div class="cards">
  {% for row in rows %}
    <article class="card{% if row.post.id == selected %} is-selected{% endif %}" data-post="{{ row.post.id }}">
      <label class="tick"><input type="checkbox" name="ids" value="{{ row.post.id }}" {% if ticked and row.post.id in ticked %}checked{% endif %} aria-label="Tick {{ row.post.id }}"></label>
      <button type="button" class="open" hx-get="/posts/{{ row.post.id }}" hx-target="#detail" hx-swap="innerHTML"
        hx-push-url="/posts?post={{ row.post.id }}">
        <div class="thumb">
          {% if row.thumb %}<img src="{{ row.thumb }}" alt="" loading="lazy">
          {% elif row.status == "draft" %}<div class="none">No picks yet</div>
          {% else %}<div class="none">Not rendered yet</div>{% endif %}
        </div>
        <div class="title">{{ row.post.title | plain or "(untitled)" }}</div>
      </button>
      <div class="meta">
        <span class="dot" data-status="{{ row.status }}"></span><span class="status">{{ row.status }}</span>
        {% if row.sent != "-" %}<span>sent {{ row.sent }}</span>{% elif row.planned != "-" %}<span>{{ row.planned }}</span>{% endif %}
      </div>
      <div class="meta">{{ "@" ~ row.post.account if row.post.account else "no account" }} · {{ row.post.id }}</div>
    </article>
  {% endfor %}
  </div>
</form>
{% else %}
<p class="empty">No posts yet. <a href="/new">Create one</a>.</p>
{% endif %}
```

Replace the body of `templates/posts.html`'s `content` block:
```html
<div class="studio">
  <section>
    <div class="toolbar">
      <h1>Posts</h1>
      <span class="spacer"></span>
      <form id="filters" class="toolbar" hx-get="/posts/table" hx-target="#posts-table" hx-trigger="change"
            hx-include="#bulk" hx-vals='js:{selected: selectedPost()}'>
        <select name="account" aria-label="Account">
          <option value="">Every account</option>
          {% for a in accounts %}
          <option value="{{ a.handle }}" {% if a.handle == account %}selected{% endif %}>{{ a.display }}</option>
          {% endfor %}
          <option value="{{ no_account }}" {% if account == no_account %}selected{% endif %}>No account</option>
        </select>
        <select name="status" aria-label="Status">
          <option value="">Any status</option>
          {% for s in statuses %}
          <option value="{{ s }}" {% if s == status %}selected{% endif %}>{{ s }}</option>
          {% endfor %}
        </select>
      </form>
      <a class="button primary" href="/new">New post</a>
    </div>
    <div id="posts-table" hx-get="/posts/table" hx-include="#filters, #bulk"
         hx-vals='js:{selected: selectedPost()}'
         hx-trigger="changed-posts from:body, changed-store from:body">
      {% include "_posts_table.html" %}
    </div>
  </section>
  <section id="detail" class="panel viewer-pane">
    {% if selected %}
    <div hx-get="/posts/{{ selected }}" hx-trigger="load" hx-swap="outerHTML"></div>
    {% else %}
    <p class="empty">Pick a post to see its slides.</p>
    {% endif %}
  </section>
</div>
```
The `test_no_posts_says_so` test looks for "No posts yet" — kept.

In `static/app.js`, replace the table-row selection handler with a card one:
```js
  document.addEventListener("click", (e) => {
    const opener = e.target.closest("#posts-table .card .open");
    if (!opener) return;
    document.querySelectorAll("#posts-table .card.is-selected").forEach((c) => c.classList.remove("is-selected"));
    opener.closest(".card").classList.add("is-selected");
  });
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/web -q`
Expected: all PASS. (`test_the_page_lists_posts_newest_first_with_their_status` checks `<span class="status">{status}</span>` — kept verbatim in the card.)

- [ ] **Step 6: Commit**

```bash
git add src/manhwatok/web tests/web
git commit -m "feat(web): posts as cover cards"
```

---

### Task 3: The slide viewer

**Files:**
- Modify: `templates/_post_detail.html`, `routes/posts.py` (`_Detail.accent`), `static/app.js`
- Test: `tests/web/test_studio.py`

**Interfaces:**
- Consumes: `_Detail` (step 1).
- Produces: `_Detail.accent: str` (the account's accent, else the post's); the detail root carries `style="--accent: {accent}"`; the viewer is `<div class="viewer" data-gallery>` with `<div class="stage"><img id="stage" src="{first slide}" alt=""></div>` and the filmstrip `<img src="{url}" data-slide aria-current="true|false">` per slide (so step 1's `data-slide` count test holds); caption, TikTok text and picks sit in `<details>` sections.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_studio.py`:
```python
def test_the_viewer_shows_the_first_slide_big_and_all_in_the_filmstrip(tmp_path):
    with client_for(_two(make_ctx(tmp_path))) as client:
        html = client.get(f"/posts/{RENDERED}").text
    stage = html[html.index('class="stage"'):]
    assert f'src="/files/{RENDERED}/01.png?v=' in stage[: stage.index("</div>")]
    assert html.count("data-slide") == 5
    assert html.count('aria-current="true"') == 1


def test_the_detail_takes_the_accounts_accent(tmp_path):
    from manhwatok.domain.account import Account

    ctx = _two(make_ctx(tmp_path))
    ctx.store.accounts.add(Account(handle="reads", accent="#ff5588"))
    ctx.tools.posts.save(ctx.tools.posts.get(RENDERED).model_copy(update={"account": "reads"}))
    with client_for(ctx) as client:
        html = client.get(f"/posts/{RENDERED}").text
    assert 'style="--accent: #ff5588"' in html
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_studio.py -q`
Expected: the two new tests FAIL.

- [ ] **Step 3: The accent**

In `routes/posts.py`, add `accent: str` as the last field of `_Detail` and pass `accent=account.accent if account else post.accent` in `_detail(...)`'s constructor call.

- [ ] **Step 4: The viewer template**

Replace `templates/_post_detail.html`:
```html
<div id="post-detail" data-post="{{ d.post.id }}" style="--accent: {{ d.accent }}" hx-get="/posts/{{ d.post.id }}"
     hx-trigger="changed-posts from:body, changed-store from:body" hx-swap="outerHTML">
  <h2>{{ d.post.title | plain or "(untitled)" }}</h2>
  <p class="meta muted"><span class="dot" data-status="{{ d.status }}"></span> {{ d.status }}
    · {{ d.account_label }} · visible to {{ d.visibility }}
    {% if d.sent != "-" %}· sent {{ d.sent }}{% elif d.planned != "-" %}· planned {{ d.planned }}{% endif %}</p>

  {% if d.post.is_unfinished %}
  <p class="empty">No picks yet. Pick titles for it from New post.</p>
  {% else %}
    {% if d.slides %}
    <div class="viewer" data-gallery>
      <div class="stage"><img id="stage" src="{{ d.slides[0] }}" alt="Slide 1" data-full="{{ d.slides[0] }}"></div>
      <div class="filmstrip">
        {% for url in d.slides %}<img src="{{ url }}" data-slide aria-current="{{ 'true' if loop.first else 'false' }}" alt="Slide {{ loop.index }}" loading="lazy">{% endfor %}
      </div>
    </div>
    {% else %}
    <p class="empty">Not rendered yet — render it to see the slides.</p>
    {% endif %}
  {% endif %}

  <div class="actions">
    <button class="button primary" hx-post="/posts/{{ d.post.id }}/render" hx-swap="none"
      {% if d.post.sent_at %}hx-confirm="Post {{ d.post.id }} was already sent. Render it again?"{% endif %}>Render</button>
    <button class="button" hx-post="/posts/{{ d.post.id }}/export" hx-swap="none">Export</button>
    <form hx-post="/posts/{{ d.post.id }}/visibility" hx-trigger="change" hx-swap="none">
      <select name="visibility" aria-label="Who can see it">
        <option value="" {% if d.post.visibility is none %}selected{% endif %}>Visible as the account says</option>
        {% for v in visibilities %}
        <option value="{{ v.value }}" {% if d.post.visibility == v %}selected{% endif %}>Visible to {{ v.spoken }}</option>
        {% endfor %}
      </select>
    </form>
    <button class="button danger" hx-post="/posts/{{ d.post.id }}/delete" hx-swap="none"
      hx-confirm="Delete post {{ d.post.id }} and its slides?">Delete</button>
  </div>

  {% if not d.post.is_unfinished %}
  <h3>Cover</h3>
  <div class="covers">
    {% for c in d.covers %}
    <figure {% if c.chosen %}class="chosen"{% endif %} hx-post="/posts/{{ d.post.id }}/cover"
      hx-vals='{"style": "{{ c.style }}"}' hx-swap="none" title="Use the {{ c.style }} cover">
      {% if c.url %}<img src="{{ c.url }}" alt="{{ c.style }} cover">{% else %}<div class="muted">Not drawn yet</div>{% endif %}
      <figcaption>{{ c.style }}</figcaption>
    </figure>
    {% endfor %}
  </div>

  <details open>
    <summary>On TikTok</summary>
    <p><strong>{{ d.title }}</strong></p>
    <div class="caption">{{ d.description }}</div>
    <p class="muted">Sounds: {{ d.sounds | join(" | ") if d.sounds else "none set" }}</p>
  </details>
  <details>
    <summary>{{ "Caption" if d.rendered else "Caption (not rendered)" }}</summary>
    <div class="caption">{{ d.caption }}</div>
  </details>
  {% endif %}
</div>
```
Step 1's detail tests keep passing: `data-slide` stays on each filmstrip image, the covers keep `class="chosen"` and `hx-post=".../cover"`, the buttons keep their `hx-post` URLs and `hx-confirm`. `test_a_draft_says_it_has_no_picks` looks for "no picks yet" — the draft text is now "No picks yet": change that test's assertion to `"No picks yet" in html`.

- [ ] **Step 5: The viewer's behaviour**

In `static/app.js`, before the lightbox code:
```js
  // Viewer: a filmstrip click puts that slide on the stage; the stage opens the lightbox on it.
  document.addEventListener("click", (e) => {
    const thumb = e.target.closest(".filmstrip [data-slide]");
    if (!thumb) return;
    e.stopPropagation();
    const viewer = thumb.closest(".viewer");
    const stage = viewer.querySelector("#stage");
    stage.src = thumb.src;
    stage.dataset.full = thumb.src;
    viewer.querySelectorAll("[data-slide]").forEach((t) => t.setAttribute("aria-current", t === thumb ? "true" : "false"));
  }, true);
  document.addEventListener("click", (e) => {
    const stage = e.target.closest(".viewer .stage");
    if (!stage) return;
    const current = stage.closest(".viewer").querySelector('[data-slide][aria-current="true"]');
    if (current) current.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
```
and change the lightbox opener so only non-filmstrip clicks reach it — the capture-phase handler above stops filmstrip clicks, and the stage re-dispatches a click on the current thumb; make the lightbox listener run for that re-dispatched event by checking `e.isTrusted === false || !e.target.closest(".filmstrip")`:
```js
  document.addEventListener("click", (e) => {
    const slide = e.target.closest("[data-slide]");
    if (!slide || (e.isTrusted && slide.closest(".filmstrip"))) return;
    slides = [...slide.closest("[data-gallery]").querySelectorAll("[data-slide]")];
    show(slides.indexOf(slide));
    box.showModal();
  });
```
(replacing the old lightbox click listener).

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/web -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/manhwatok/web tests/web
git commit -m "feat(web): a slide viewer with a filmstrip, in the account's accent"
```

---

### Task 4: New post — the page and the search

**Files:**
- Create: `src/manhwatok/web/drafts.py`, `src/manhwatok/web/routes/new.py`, `templates/new.html`, `templates/_new_results.html`
- Modify: `src/manhwatok/web/server.py` (`app.state.drafts`, include `new.router`)
- Test: `tests/web/test_new.py`

**Interfaces:**
- Consumes: `suggest_for_account(query, account, metadata, chapters, history, now, allow_repeats=False, progress=...) -> list[Manhwa]` (`manhwatok.app.suggest`), `prefill_items(candidates) -> list[PostItem]` (`manhwatok.app.build_post`), `SearchQuery(tags, genres, sort, limit, min_tag_rank)` and `Sort` (`manhwatok.domain.models`), `split_names` (`manhwatok.domain.text`), `chapter_label` (`manhwatok.domain.labels`), `MAX_ITEMS`, `DEFAULT_HASHTAGS`, `DEFAULT_ACCENT` (`manhwatok.domain.post`), `ArtStyle`, `CoverStyle`.
- Produces:
  - `drafts.Draft` dataclass: `id: str`, `candidates: list[Manhwa]`, `account: str | None`, `theme: str | None`.
  - `drafts.Drafts(keep: int = 20)`: `add(candidates, account, theme) -> Draft`, `get(draft_id) -> Draft` (raises `ManhwatokError("this search is gone — search again")`).
  - `GET /new` (page `"new"`), `POST /new/search` (form: `account`, `theme`, `tags`, `genres`, `sort`, `min_rank`, `limit`, `repeats`, `chapters`, `title`) → `_new_results.html` into `#results`, or a notice on error.
  - `_new_results.html` markup Task 5 relies on: `<form id="picks-form" hx-post="/new/save" hx-swap="none">` with `<input type="hidden" name="draft" value="{id}">`; each candidate `<div class="candidate" role="button" tabindex="0" data-id="{anilist_id}" aria-pressed="true|false">`; the picks list `<ol class="picks" id="picks">` with `<li class="pick" draggable="true" data-id="{id}"><input type="hidden" name="pick" value="{id}"> … <input name="hook-{id}" value="{hook}"> …</li>`; a `<template id="pick-template">` per candidate (`<template data-id="{id}">`) holding its `<li>` for adding back.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_new.py`:
```python
import json

import pytest

pytest.importorskip("fastapi")

from manhwatok.domain.account import Account  # noqa: E402
from manhwatok.domain.theme import Theme  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import FakeMetadata, manhwa  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402


def _results():
    return [
        manhwa(anilist_id=1, title="Solo Leveling", chapters=200, genres=["Action"],
               description="A weak hunter becomes the strongest. More text."),
        manhwa(anilist_id=2, title='Evil <script>alert("x")</script>', chapters=80,
               description='He said "run". Then ran.'),
        manhwa(anilist_id=3, title="Omniscient Reader", chapters=150),
    ]


def _ctx(tmp_path, results=None):
    ctx = make_ctx(tmp_path, metadata=FakeMetadata(results=_results() if results is None else results))
    ctx.store.accounts.add(Account(handle="reads"))
    ctx.store.themes.add(Theme(name="regression", tags=["Time Manipulation"], title="Regression *hits*"))
    return ctx


def _notice(response):
    return json.loads(response.headers["HX-Trigger"])["notice"]


def test_the_page_offers_accounts_and_themes(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        html = client.get("/new").text
    assert '<a href="/new" aria-current="page"' in html
    assert '<option value="reads">@reads</option>' in html
    assert 'value="regression"' in html and 'data-title="Regression *hits*"' in html
    assert 'hx-post="/new/search"' in html and 'id="results"' in html


def test_a_search_by_tags_shows_every_result_picked_with_its_hook(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post("/new/search", data={"account": "reads", "tags": "Regression, Revenge",
                                                     "limit": "12", "chapters": "on"})
    html = response.text
    query = ctx.metadata.queries[0]
    assert (query.tags, query.limit, query.sort.value, query.min_tag_rank) == (
        ["Regression", "Revenge"], 12, "score", 60)
    assert html.count('class="candidate"') == 3
    assert html.count('aria-pressed="true"') == 3  # the TUI's prefill: every result, in order
    assert html.count('<li class="pick"') == 3
    assert 'name="hook-1" value="A weak hunter becomes the strongest."' in html
    draft = client.app.state.drafts.get(html.split('name="draft" value="')[1].split('"')[0])
    assert [m.anilist_id for m in draft.candidates] == [1, 2, 3] and draft.account == "reads"


def test_candidate_text_is_escaped(tmp_path):
    with client_for(_ctx(tmp_path)) as client:
        html = client.post("/new/search", data={"tags": "x"}).text
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert 'value="He said &#34;run&#34;."' in html


def test_a_theme_search_uses_the_theme(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        client.post("/new/search", data={"theme": "regression", "limit": "5"})
    query = ctx.metadata.queries[0]
    assert (query.tags, query.limit) == (["Time Manipulation"], 5)


@pytest.mark.parametrize(
    ("form", "message"),
    [
        ({}, "pick a theme or give at least one tag or genre"),
        ({"theme": "regression", "tags": "x"}, "use either a theme or tags/genres, not both"),
        ({"tags": "x", "limit": "99"}, "How many must be 1–50"),
        ({"tags": "x", "min_rank": "abc"}, "Min tag rank must be a number"),
    ],
)
def test_a_search_that_cannot_run_says_why(tmp_path, form, message):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post("/new/search", data=form)
    assert _notice(response) == {"text": message, "level": "error"}
    assert ctx.metadata.queries == []


def test_an_anilist_failure_is_a_notice(tmp_path):
    from manhwatok.domain.errors import MetadataError

    class Down(FakeMetadata):
        def search(self, query):
            raise MetadataError("AniList timed out")

    ctx = make_ctx(tmp_path, metadata=Down())
    with client_for(ctx) as client:
        response = client.post("/new/search", data={"tags": "x"})
    assert _notice(response) == {"text": "AniList timed out", "level": "error"}


def test_no_results_says_what_to_try(tmp_path):
    with client_for(_ctx(tmp_path, results=[])) as client:
        html = client.post("/new/search", data={"tags": "x"}).text
    assert "Nothing matched" in html


def test_drafts_keep_the_latest_searches_only():
    from manhwatok.domain.errors import ManhwatokError
    from manhwatok.web.drafts import Drafts

    drafts = Drafts(keep=2)
    first = drafts.add([manhwa()], None, None)
    drafts.add([manhwa()], None, None)
    drafts.add([manhwa()], None, None)
    with pytest.raises(ManhwatokError) as e:
        drafts.get(first.id)
    assert str(e.value) == "this search is gone — search again"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_new.py -v`
Expected: FAIL — 404 on `/new`, `ModuleNotFoundError: manhwatok.web.drafts`.

- [ ] **Step 3: The drafts store**

`src/manhwatok/web/drafts.py`:
```python
"""A search's candidates, kept between the search and the save: the page only posts back which
titles it picked, in what order, with what hooks. In memory — a restart forgets them, and the
page is told to search again."""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass

from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Manhwa


@dataclass
class Draft:
    id: str
    candidates: list[Manhwa]
    account: str | None
    theme: str | None


class Drafts:
    def __init__(self, keep: int = 20) -> None:
        self._keep = keep
        self._lock = threading.Lock()
        self._drafts: OrderedDict[str, Draft] = OrderedDict()

    def add(self, candidates: list[Manhwa], account: str | None, theme: str | None) -> Draft:
        draft = Draft(secrets.token_urlsafe(8), list(candidates), account, theme)
        with self._lock:
            self._drafts[draft.id] = draft
            while len(self._drafts) > self._keep:
                self._drafts.popitem(last=False)
        return draft

    def get(self, draft_id: str) -> Draft:
        with self._lock:
            draft = self._drafts.get(draft_id)
        if draft is None:
            raise ManhwatokError("this search is gone — search again")
        return draft
```
In `server.py`: `from manhwatok.web.drafts import Drafts`; in `create_app`, `app.state.drafts = Drafts()`; include `new.router` (`from manhwatok.web.routes import files, header, new, posts`).

- [ ] **Step 4: The route**

`src/manhwatok/web/routes/new.py`:
```python
"""New post: search as the TUI's Build does (an account's filters and history, a theme or
tags/genres), pick and order the titles in the page, then save and render."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.app.build_post import prefill_items
from manhwatok.app.suggest import suggest_for_account
from manhwatok.domain.account import Account
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.labels import chapter_label
from manhwatok.domain.models import ArtStyle, CoverStyle, SearchQuery, Sort
from manhwatok.domain.post import DEFAULT_ACCENT, DEFAULT_HASHTAGS, MAX_ITEMS
from manhwatok.domain.text import split_names
from manhwatok.web.routes.common import ctx_of, done, page, trigger

router = APIRouter()


def _number(text: str, name: str, low: int, high: int, default: int | None) -> int | None:
    text = text.strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        raise ManhwatokError(f"{name} must be a number") from None
    if not low <= value <= high:
        raise ManhwatokError(f"{name} must be {low}–{high}")
    return value


def _query(ctx, theme: str, tags: str, genres: str, sort: str, min_rank: str, limit: str):
    """The TUI Build's rules: a theme, or tags/genres — never both, never neither."""
    how_many = _number(limit, "How many", 1, 50, 12)
    rank = _number(min_rank, "Min tag rank", 0, 100, None)
    order = Sort(sort) if sort else None
    tag_list, genre_list = split_names(tags), split_names(genres)
    if theme:
        if tag_list or genre_list:
            raise ManhwatokError("use either a theme or tags/genres, not both")
        query = ctx.store.themes.get(theme).to_query(how_many)
        updates = {k: v for k, v in (("sort", order), ("min_tag_rank", rank)) if v is not None}
        return query.model_copy(update=updates)
    if not (tag_list or genre_list):
        raise ManhwatokError("pick a theme or give at least one tag or genre")
    return SearchQuery(
        tags=tag_list,
        genres=genre_list,
        sort=order or Sort.SCORE,
        limit=how_many,
        min_tag_rank=60 if rank is None else rank,
    )


def _account(ctx, handle: str) -> Account | None:
    return ctx.store.accounts.get(handle) if handle else None


@router.get("/new", response_class=HTMLResponse)
def new_page(request: Request) -> HTMLResponse:
    ctx = ctx_of(request)
    return page(
        request,
        "new.html",
        page="new",
        accounts=ctx.store.accounts.list(),
        themes=ctx.store.themes.list(),
        sorts=list(Sort),
    )


@router.post("/new/search", response_class=HTMLResponse)
def search(
    request: Request,
    account: str = Form(""),
    theme: str = Form(""),
    tags: str = Form(""),
    genres: str = Form(""),
    sort: str = Form(""),
    min_rank: str = Form(""),
    limit: str = Form(""),
    repeats: str = Form(""),
    chapters: str = Form(""),
    title: str = Form(""),
) -> Response:
    ctx = ctx_of(request)
    try:
        query = _query(ctx, theme, tags, genres, sort, min_rank, limit)
        who = _account(ctx, account)
        results = suggest_for_account(
            query,
            who,
            ctx.metadata,
            ctx.chapters if chapters else None,
            ctx.store.history,
            request.app.state.clock(),
            bool(repeats),
        )
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")
    draft = request.app.state.drafts.add(results, who.handle if who else None, theme or None)
    if not title and theme:
        title = ctx.store.themes.get(theme).title
    return page(
        request,
        "_new_results.html",
        draft=draft,
        picks=prefill_items(results),
        picked={m.anilist_id for m in results[:MAX_ITEMS]},
        label=chapter_label,
        title=title,
        account=who,
        defaults={"hashtags": DEFAULT_HASHTAGS, "accent": DEFAULT_ACCENT},
        arts=list(ArtStyle),
        covers=list(CoverStyle),
        max_items=MAX_ITEMS,
    )
```
(`trigger` is imported for Task 5.) If `ThemeRepository` has no `list()`, use the method the TUI's Themes tab uses to list themes (`grep -n "def " src/manhwatok/ports/store.py`) and rule it in the ledger.

- [ ] **Step 5: The templates**

`templates/new.html`:
```html
{% extends "base.html" %}
{% block title %}New post · manhwatok{% endblock %}
{% block content %}
<h1>New post</h1>
<form class="panel search" hx-post="/new/search" hx-target="#results" hx-swap="innerHTML"
      hx-indicator="#searching">
  <label class="field">Account
    <select name="account">
      <option value="">No account</option>
      {% for a in accounts %}<option value="{{ a.handle }}">{{ a.display }}</option>{% endfor %}
    </select>
  </label>
  <label class="field">Theme
    <select name="theme" id="theme">
      <option value="" data-title="">No theme — use tags or genres</option>
      {% for t in themes %}<option value="{{ t.name }}" data-title="{{ t.title }}">{{ t.name }}</option>{% endfor %}
    </select>
  </label>
  <label class="field">Tags <input name="tags" placeholder="Regression, Revenge"></label>
  <label class="field">Genres <input name="genres" placeholder="Action, Fantasy"></label>
  <label class="field">Sort
    <select name="sort"><option value="">Score</option>{% for s in sorts %}<option value="{{ s.value }}">{{ s.value | capitalize }}</option>{% endfor %}</select>
  </label>
  <label class="field">How many <input name="limit" inputmode="numeric" placeholder="12"></label>
  <label class="field">Min tag rank <input name="min_rank" inputmode="numeric" placeholder="60"></label>
  <label class="field">Title <input name="title" id="title" placeholder="Manhwa where the MC *regresses*"></label>
  <div class="wide">
    <label><input type="checkbox" name="chapters" checked> Fill chapter counts</label>
    <label><input type="checkbox" name="repeats"> Allow titles posted recently</label>
    <span class="spacer"></span>
    <span id="searching" class="htmx-indicator muted">Searching AniList…</span>
    <button class="button primary">Find titles</button>
  </div>
</form>
<div id="results"><p class="empty">Choose a theme or some tags, then find titles.</p></div>
{% endblock %}
```

`templates/_new_results.html`:
```html
{% if not draft.candidates %}
<p class="empty">Nothing matched. Try fewer tags, a lower min tag rank, or allow recent titles.</p>
{% else %}
<form id="picks-form" class="new" hx-post="/new/save" hx-swap="none">
  <input type="hidden" name="draft" value="{{ draft.id }}">
  <section>
    <p class="muted">Click a title to pick or drop it. {{ draft.candidates | length }} found; up to {{ max_items }} picks.</p>
    <div class="search" id="candidates">
      {% for m in draft.candidates %}
      <div class="candidate" role="button" tabindex="0" data-id="{{ m.anilist_id }}"
           aria-pressed="{{ 'true' if m.anilist_id in picked else 'false' }}">
        <div class="thumb">{% if m.cover_url %}<img src="{{ m.cover_url }}" alt="" loading="lazy" referrerpolicy="no-referrer">{% endif %}</div>
        <span class="rank"></span>
        <div class="title">{{ m.title }}</div>
        <div class="meta">{{ label(m) }}{% if m.genres %} · {{ m.genres[:3] | join(", ") }}{% endif %}</div>
        <template data-id="{{ m.anilist_id }}">
          <li class="pick" draggable="true" data-id="{{ m.anilist_id }}">
            <input type="hidden" name="pick" value="{{ m.anilist_id }}">
            {% if m.cover_url %}<img src="{{ m.cover_url }}" alt="" referrerpolicy="no-referrer">{% else %}<span></span>{% endif %}
            <div><div class="name">{{ m.title }}</div>
              <input name="hook-{{ m.anilist_id }}" value="" placeholder="Hook line" aria-label="Hook for {{ m.title }}"></div>
            <div class="moves">
              <button type="button" data-move="up" aria-label="Move {{ m.title }} up">↑</button>
              <button type="button" data-move="down" aria-label="Move {{ m.title }} down">↓</button>
            </div>
          </li>
        </template>
      </div>
      {% endfor %}
    </div>
  </section>
  <section class="panel">
    <label class="field">Title <input name="title" value="{{ title }}" required placeholder="Manhwa where the MC *regresses*"></label>
    <h3>Picks, in order</h3>
    <ol class="picks" id="picks">
      {% for item in picks %}
      <li class="pick" draggable="true" data-id="{{ item.manhwa.anilist_id }}">
        <input type="hidden" name="pick" value="{{ item.manhwa.anilist_id }}">
        {% if item.manhwa.cover_url %}<img src="{{ item.manhwa.cover_url }}" alt="" referrerpolicy="no-referrer">{% else %}<span></span>{% endif %}
        <div><div class="name">{{ item.manhwa.title }}</div>
          <input name="hook-{{ item.manhwa.anilist_id }}" value="{{ item.hook }}" placeholder="Hook line" aria-label="Hook for {{ item.manhwa.title }}"></div>
        <div class="moves">
          <button type="button" data-move="up" aria-label="Move {{ item.manhwa.title }} up">↑</button>
          <button type="button" data-move="down" aria-label="Move {{ item.manhwa.title }} down">↓</button>
        </div>
      </li>
      {% endfor %}
    </ol>
    <details>
      <summary>Style</summary>
      <div class="style">
        <label class="field">Hashtags <input name="hashtags" placeholder="{{ account.hashtags if account else defaults.hashtags }}"></label>
        <label class="field">Accent <input name="accent" placeholder="{{ account.accent if account else defaults.accent }}"></label>
        <label class="field">Emojis <input name="emojis" placeholder="{{ account.emojis if account and account.emojis else 'none' }}"></label>
        <label class="field">Art
          <select name="art"><option value="">As the account says</option>{% for a in arts %}<option value="{{ a.value }}">{{ a.value }}</option>{% endfor %}</select>
        </label>
        <label class="field">Cover
          <select name="cover">{% for c in covers %}<option value="{{ c.value }}">{{ c.value }}</option>{% endfor %}</select>
        </label>
      </div>
    </details>
    <div class="actions"><button class="button primary">Save and render</button></div>
  </section>
</form>
{% endif %}
```
Jinja escapes `m.title`, `m.cover_url` and `item.hook` (attribute values included: `"` becomes `&#34;`), which the escaping test checks.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/web/test_new.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/manhwatok/web tests/web/test_new.py
git commit -m "feat(web): New post — search as the TUI's Build does, results as cover cards"
```

---

### Task 5: New post — picking in the page, save and render

**Files:**
- Modify: `src/manhwatok/web/routes/new.py` (save), `static/app.js` (picks editor, theme title)
- Test: `tests/web/test_new.py`

**Interfaces:**
- Consumes: `Drafts.get` (Task 4), `store_new_post(candidates, title, items, account, hashtags, accent, posts, now, art=None, emojis=None, theme=None, cover=CoverStyle.FAN) -> ListPost` (`manhwatok.app.build_post`), `PostItem` (`manhwatok.domain.post`), `render_post`, `RENDER`, `Busy`, `trigger`, `done`.
- Produces: `POST /new/save` (form: `draft`, `title`, repeated `pick` in order, `hook-<id>`, `hashtags`, `accent`, `emojis`, `art`, `cover`) → on success an `HX-Redirect: /posts?post=<id>` response with a notice, the render started in the render lane (or, when that lane is busy, the post saved and the notice saying so); errors → a notice, nothing saved.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_new.py`:
```python
from tests.web.helpers import wait_job  # noqa: E402


def _search(client, **form):
    html = client.post("/new/search", data={"account": "reads", "tags": "x", **form}).text
    return html.split('name="draft" value="')[1].split('"')[0]


def test_saving_keeps_the_posted_order_and_hooks_and_renders(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        draft = _search(client)
        response = client.post("/new/save", data={
            "draft": draft, "title": "Manhwa where the MC *wins*",
            "pick": ["3", "1"], "hook-3": "He read it all.", "hook-1": "Weakest to strongest.",
            "hook-2": "never picked", "hashtags": "", "accent": "", "emojis": "", "art": "",
            "cover": "hero",
        })
        post_id = response.headers["HX-Redirect"].split("post=")[1]
        job = wait_job(client, client.app.state.jobs.recent()[0].id)
    post = ctx.tools.posts.get(post_id)
    assert [(i.manhwa.anilist_id, i.hook) for i in post.items] == [
        (3, "He read it all."), (1, "Weakest to strongest.")]
    assert (post.title, post.account, post.cover.value) == ("Manhwa where the MC *wins*", "reads", "hero")
    assert [m.anilist_id for m in post.candidates] == [1, 2, 3]
    assert _notice(response)["text"] == f"saved post {post_id} — rendering it…"
    assert job.outcome == f"rendered post {post_id}"
    assert (ctx.tools.posts.folder(post_id) / "01.png").is_file()


def test_a_theme_search_saves_the_theme_on_the_post(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        html = client.post("/new/search", data={"theme": "regression"}).text
        draft = html.split('name="draft" value="')[1].split('"')[0]
        response = client.post("/new/save", data={"draft": draft, "title": "T", "pick": ["1"]})
        wait_job(client, client.app.state.jobs.recent()[0].id)
    post_id = response.headers["HX-Redirect"].split("post=")[1]
    assert ctx.tools.posts.get(post_id).theme == "regression"


@pytest.mark.parametrize(
    ("form", "message"),
    [
        ({"title": "", "pick": ["1"]}, "title"),  # check_picks: a title is needed
        ({"title": "T"}, "pick"),  # no picks
        ({"title": "T", "pick": ["1", "1"]}, "twice"),
        ({"title": "T", "pick": ["99"]}, "not in this search"),
        ({"title": "T", "pick": ["1"], "accent": "blue"}, "accent"),
    ],
)
def test_a_save_that_cannot_go_through_says_why_and_saves_nothing(tmp_path, form, message):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        draft = _search(client)
        response = client.post("/new/save", data={"draft": draft, **form})
    notice = _notice(response)
    assert notice["level"] == "error" and message in notice["text"].lower()
    assert "HX-Redirect" not in response.headers
    assert ctx.tools.posts.list() == []


def test_a_search_that_is_gone_asks_to_search_again(tmp_path):
    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        response = client.post("/new/save", data={"draft": "old", "title": "T", "pick": ["1"]})
    assert _notice(response) == {"text": "this search is gone — search again", "level": "error"}
    assert ctx.tools.posts.list() == []


def test_a_save_during_another_render_saves_and_says_to_render_later(tmp_path):
    import threading

    from manhwatok.web.jobs import RENDER

    ctx = _ctx(tmp_path)
    with client_for(ctx) as client:
        draft = _search(client)
        release = threading.Event()
        job = client.app.state.jobs.start(
            RENDER, "render post a", lambda io: release.wait(5) and "ok"
        )
        response = client.post("/new/save", data={"draft": draft, "title": "T", "pick": ["1"]})
        release.set()
        wait_job(client, job.id)
    post_id = response.headers["HX-Redirect"].split("post=")[1]
    assert _notice(response) == {
        "text": f"saved post {post_id} — render it when render post a is done",
        "level": "warning",
    }
    assert ctx.tools.posts.get(post_id).items[0].manhwa.anilist_id == 1
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_new.py -q`
Expected: the save tests FAIL (404 on `/new/save`).

- [ ] **Step 3: The save route**

Append to `routes/new.py` (and add the imports at the top: `from dataclasses import replace`, `from manhwatok.app.build_post import store_new_post` alongside `prefill_items`, `from manhwatok.app.render_post import render_post`, `from manhwatok.domain.post import PostItem`, `from manhwatok.web.jobs import RENDER, Busy`):
```python
@router.post("/new/save")
async def save(request: Request) -> Response:
    """Save the picks as a new post, then render it. The order of the posted `pick` fields is
    the order of the post; each pick's hook comes from its `hook-<id>` field."""
    form = await request.form()
    ctx = ctx_of(request)
    try:
        draft = request.app.state.drafts.get(str(form.get("draft", "")))
        by_id = {str(m.anilist_id): m for m in draft.candidates}
        picks = [str(p) for p in form.getlist("pick")]
        missing = [p for p in picks if p not in by_id]
        if missing:
            raise ManhwatokError(f"title {missing[0]} is not in this search — search again")
        items = [
            PostItem(manhwa=by_id[p], hook=str(form.get(f"hook-{p}", "")).strip()) for p in picks
        ]
        text = {name: str(form.get(name, "")).strip() for name in ("hashtags", "accent", "emojis")}
        art = str(form.get("art", ""))
        post = store_new_post(
            draft.candidates,
            str(form.get("title", "")).strip(),
            items,
            _account(ctx, draft.account or ""),
            text["hashtags"] or None,
            text["accent"] or None,
            ctx.tools.posts,
            request.app.state.clock(),
            art=ArtStyle(art) if art else None,
            emojis=text["emojis"] or None,
            theme=draft.theme,
            cover=CoverStyle(str(form.get("cover", "")) or CoverStyle.FAN.value),
        )
    except (ManhwatokError, ValueError) as e:
        return done(request, str(e), "error")
    request.app.state.bus.publish("changed", what="posts")
    bus = request.app.state.bus

    def work(io) -> str:
        slides = render_post(post.id, replace(ctx.tools, progress=io.progress))
        io.progress(f"post {post.id} · {len(slides)} slides")
        bus.publish("changed", what="posts")
        return f"rendered post {post.id}"

    try:
        request.app.state.jobs.start(RENDER, f"render post {post.id}", work)
        text_, level = f"saved post {post.id} — rendering it…", "info"
    except Busy:
        running = request.app.state.jobs.busy(RENDER)
        text_ = f"saved post {post.id} — render it when {running.heading} is done"
        level = "warning"
    response = trigger(Response(status_code=200), text_, level, changed=["posts"])
    response.headers["HX-Redirect"] = f"/posts?post={post.id}"
    return response
```
(`running` can be None if the other render ended in between; then use `f"saved post {post.id} — render it from Posts"`. Handle that with `running.heading if running else "the other render"`.)

`check_picks` raises `DraftError` for a blank title ("…title…"), no picks ("…pick…" / "no items"), a title picked twice ("…twice…"); `check_accent` raises `InvalidName` naming the accent. If a message doesn't contain the word the test looks for, match the test to the real message and rule it in the ledger.

- [ ] **Step 4: The picks editor in the page**

Append to `static/app.js` (inside the IIFE, before its end):
```js
  // New post: the theme fills the title unless one was typed.
  document.addEventListener("change", (e) => {
    if (e.target.id !== "theme") return;
    const title = document.getElementById("title");
    const themed = e.target.selectedOptions[0].dataset.title;
    if (title && themed && !title.value) title.value = themed;
  });

  // New post: click a candidate to pick or drop it; the picks list follows.
  function toggle(card) {
    const list = document.getElementById("picks");
    const id = card.dataset.id;
    const picked = card.getAttribute("aria-pressed") === "true";
    if (picked) {
      list.querySelector(`.pick[data-id="${id}"]`)?.remove();
      card.setAttribute("aria-pressed", "false");
    } else {
      const template = card.querySelector("template");
      list.append(template.content.firstElementChild.cloneNode(true));
      card.setAttribute("aria-pressed", "true");
    }
    ranks();
  }
  function ranks() {
    const order = [...document.querySelectorAll("#picks .pick")].map((li) => li.dataset.id);
    document.querySelectorAll("#candidates .candidate").forEach((card) => {
      card.querySelector(".rank").textContent = order.indexOf(card.dataset.id) + 1 || "";
    });
  }
  document.addEventListener("click", (e) => {
    const card = e.target.closest("#candidates .candidate");
    if (card) return toggle(card);
    const move = e.target.closest("#picks [data-move]");
    if (!move) return;
    const li = move.closest(".pick");
    if (move.dataset.move === "up" && li.previousElementSibling) li.previousElementSibling.before(li);
    if (move.dataset.move === "down" && li.nextElementSibling) li.nextElementSibling.after(li);
    ranks();
  });
  document.addEventListener("keydown", (e) => {
    const card = e.target.closest?.("#candidates .candidate");
    if (card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggle(card); }
  });
  // Drag a pick to reorder.
  let dragged = null;
  document.addEventListener("dragstart", (e) => {
    dragged = e.target.closest?.("#picks .pick");
    if (dragged) dragged.classList.add("dragging");
  });
  document.addEventListener("dragend", () => { dragged?.classList.remove("dragging"); dragged = null; ranks(); });
  document.addEventListener("dragover", (e) => {
    const over = e.target.closest?.("#picks .pick");
    if (!dragged || !over || over === dragged) return;
    e.preventDefault();
    const box = over.getBoundingClientRect();
    if (e.clientY < box.top + box.height / 2) over.before(dragged); else over.after(dragged);
  });
  document.body.addEventListener("htmx:afterSwap", (e) => { if (e.detail.target.id === "results") ranks(); });
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/web -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/manhwatok/web tests/web/test_new.py
git commit -m "feat(web): pick, order and hook titles in the page, then save and render"
```

---

### Task 6: Look at it, fix what the screenshots show, document it

- [ ] **Step 1: Screenshots**

Start `uv run manhwatok web --no-open` and take headless-Chrome screenshots (Playwright, `channel="chrome"`, 1440×900) of: `/posts?post=<a rendered post>`, `/new` empty, `/new` after a real search (a tag like `Regression`; this calls AniList), and the picks panel after moving a pick and dropping one. Check: nothing overflows, text is readable, the accent shows, the status dots read, the empty states say what to do, keyboard focus is visible (tab through /new). Fix what's off; each fix that changes behaviour gets a test first.

- [ ] **Step 2: A real post, end to end, without touching TikTok**

In the browser (headless): search, drop one pick, move one, type a hook, Save and render; the page lands on the post with its slides after the render. Then delete that test post from the page (it's the user's real data folder — leave nothing behind).

- [ ] **Step 3: Docs and the full suite**

README "Web app" section: replace "so far the **Posts** page" paragraph's last sentence with the New post flow and the look (one short paragraph). Run `uv run pytest -q -m "not browser"`; expect all pass.

- [ ] **Step 4: Commit**

```bash
git add README.md src/manhwatok/web tests/web
git commit -m "docs: the web app's studio look and New post"
```
