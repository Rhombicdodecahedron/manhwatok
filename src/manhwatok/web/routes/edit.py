"""Edit a post: its texts and look, its picks, and each title's picture. Every change goes
through the same app functions as the TUI and the CLI, then re-renders the post in the render
lane — one job per change, refused while another render runs."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from starlette.datastructures import UploadFile  # what request.form() gives

from manhwatok.adapters.picture_download import download_picture, looks_like_url
from manhwatok.app.art_options import list_art, looks, use_art
from manhwatok.app.edit_post import TEXT_FIELDS, update_picks, update_post_texts
from manhwatok.app.item_art import clear_item_art, set_item_art
from manhwatok.app.post_tools import PostTools
from manhwatok.app.render_post import render_from_source, render_post, restyle, set_cover
from manhwatok.domain.errors import DraftError, ManhwatokError, PostNotFound
from manhwatok.domain.labels import chapter_label
from manhwatok.domain.models import ArtOrder, ArtSourceName, ArtStyle, CoverStyle
from manhwatok.domain.post import MAX_ITEMS, ListPost, PostItem
from manhwatok.domain.text import first_sentence
from manhwatok.web.jobs import RENDER, Busy
from manhwatok.web.routes.common import ctx_of, done, page
from manhwatok.web.routes.files import file_url
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
        title = post.title  # as saved now: the texts form may have changed it since
    except ManhwatokError as e:
        return done(request, str(e), "error")

    def change(tools) -> str:
        update_picks(post_id, title, items, tools)  # checks the picks, saves, renders
        return "saved the picks"

    return start_change(request, post_id, "saved the picks", change, render=False)


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
    request: Request,
    post_id: str,
    anilist_id: int,
    source: str = "",
    order: str = "",
    tag: str = "",
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
            if looks(given) is None:  # checked before the title's old art is removed
                shutil.rmtree(folder, ignore_errors=True)
                raise ManhwatokError(f"{upload.filename} isn't a picture that can be read")
        elif looks_like_url(url):
            folder, given = Path(tempfile.mkdtemp(prefix="manhwatok-url-")), None
        else:
            raise ManhwatokError("give a picture file or an http(s) link")
    except ManhwatokError as e:
        return done(request, str(e), "error")

    def change(tools) -> str:
        try:
            picture = given or download_picture(url, folder)
            if looks(picture) is None:  # before the title's old art is removed
                raise ManhwatokError(f"{url} didn't give a picture that can be read")
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
