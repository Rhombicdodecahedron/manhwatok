"""Build: search for candidates (an account's filters, a theme or tags/genres), pick them in
the picks editor, save and render the new post."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, get_current_worker

from manhwatok.app.build_post import prefill_items, save_new_post
from manhwatok.app.suggest import suggest_for_account
from manhwatok.domain.account import Account
from manhwatok.domain.color import check_accent
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import Manhwa, SearchQuery, Sort, TagInfo
from manhwatok.domain.post import DEFAULT_ACCENT, DEFAULT_HASHTAGS
from manhwatok.domain.text import split_names
from manhwatok.tui.screens.picks import PicksScreen

MAX_TAG_HITS = 30


def _number(raw: str, name: str, low: int, high: int, default: int | None) -> int | None:
    if not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        value = low - 1
    if not low <= value <= high:
        raise ManhwatokError(f"{name} must be a whole number from {low} to {high}")
    return value


def matching_tags(tags: list[TagInfo], search: str) -> list[TagInfo]:
    """Tags whose name or description contains `search`, names first, at most MAX_TAG_HITS."""
    s = search.strip().casefold()
    if not s:
        return []
    by_name = [t for t in tags if s in t.name.casefold()]
    by_text = [t for t in tags if t not in by_name and s in t.description.casefold()]
    return (sorted(by_name, key=lambda t: t.name) + by_text)[:MAX_TAG_HITS]


class BuildPane(VerticalScroll):
    DEFAULT_CSS = """
    BuildPane { padding: 0 1; }
    BuildPane .row { height: auto; }
    BuildPane .field { width: 1fr; height: auto; padding-right: 1; }
    BuildPane .field Label { color: $text-muted; }
    BuildPane .narrow { width: 18; }
    BuildPane Checkbox { margin-top: 1; }
    BuildPane #search { margin: 1 0; }
    BuildPane #status { height: auto; color: $text-muted; }
    BuildPane #tag-hits { height: 10; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._auto_title = ""
        self._tags: list[TagInfo] | None = None
        self._loading_tags = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="row"):
            with Vertical(classes="field"):
                yield Label("Account (its filters, style and repeat window)")
                yield Select([], prompt="no account", id="account")
            with Vertical(classes="field"):
                yield Label("Theme — or tags/genres below")
                yield Select([], prompt="no theme", id="theme")
        with Horizontal(classes="row"):
            with Vertical(classes="field"):
                yield Label("Tags (comma-separated, all must match)")
                yield Input(id="tags")
            with Vertical(classes="field"):
                yield Label("Genres (comma-separated, all must match)")
                yield Input(id="genres")
        with Horizontal(classes="row"):
            with Vertical(classes="field"):
                yield Label("Sort")
                yield Select([(s.value, s) for s in Sort], prompt="default", id="sort")
            with Vertical(classes="field narrow"):
                yield Label("Min tag rank")
                yield Input(placeholder="60", type="integer", id="min-rank")
            with Vertical(classes="field narrow"):
                yield Label("How many")
                yield Input(placeholder="12", type="integer", id="limit")
            yield Checkbox("Allow repeats", id="repeats")
            yield Checkbox("Chapter counts", value=True, id="chapters")
        with Horizontal(classes="row"):
            with Vertical(classes="field"):
                yield Label("Title (*word* = accent colour)")
                yield Input(id="title")
        with Horizontal(classes="row"):
            with Vertical(classes="field"):
                yield Label("Hashtags")
                yield Input(id="hashtags")
            with Vertical(classes="field narrow"):
                yield Label("Accent")
                yield Input(id="accent")
            with Vertical(classes="field"):
                yield Label("Song")
                yield Input(id="song")
        yield Button("Search", id="search", variant="primary")
        yield Static("", id="status", markup=False)
        yield Label("Find a tag (enter adds it to Tags)")
        yield Input(placeholder="e.g. revenge", id="tag-search")
        yield OptionList(id="tag-hits")

    def on_mount(self) -> None:
        self.refresh_data()
        self._show_defaults(None)

    def focus_main(self) -> None:
        self.query_one("#account", Select).focus()

    def refresh_data(self) -> None:
        """Reload the account and theme choices, keeping the current picks when they still exist."""
        store = self.app.ctx.store
        try:
            accounts = store.accounts.list()
            themes = store.themes.list()
        except ManhwatokError as e:
            self.app.fail(e)
            return
        for select_id, options in [
            ("#account", [(a.display, a.handle) for a in accounts]),
            ("#theme", [(t.name, t.name) for t in themes]),
        ]:
            select = self.query_one(select_id, Select)
            keep = select.selection
            with select.prevent(Select.Changed):
                select.set_options(options)
                if keep in {value for _, value in options}:
                    select.value = keep

    def _input(self, name: str) -> Input:
        return self.query_one(f"#{name}", Input)

    def _account(self) -> Account | None:
        handle = self.query_one("#account", Select).selection
        return self.app.ctx.store.accounts.get(handle) if handle else None

    def on_select_changed(self, event: Select.Changed) -> None:
        try:
            if event.select.id == "account":
                self._show_defaults(self._account())
            elif event.select.id == "theme":
                self._theme_changed(event.select.selection)
        except ManhwatokError as e:
            self.app.fail(e)

    def _show_defaults(self, account: Account | None) -> None:
        """Blank style fields use the account's values (or the standard ones): show them."""
        self._input("hashtags").placeholder = account.hashtags if account else DEFAULT_HASHTAGS
        self._input("accent").placeholder = account.accent if account else DEFAULT_ACCENT
        song = account.song if account else ""
        self._input("song").placeholder = f"{song} (the account's)" if song else "no song"

    def _theme_changed(self, name: str | None) -> None:
        title = self._input("title")
        new = self.app.ctx.store.themes.get(name).title if name else ""
        if title.value in ("", self._auto_title):
            title.value = new
        self._auto_title = new
        for field in ("tags", "genres"):
            self._input(field).placeholder = "from the theme" if name else ""

    def _set_status(self, text: str) -> None:
        """Update status text on the main thread."""
        self.query_one("#status", Static).update(text)

    def _query(self) -> SearchQuery:
        theme = self.query_one("#theme", Select).selection
        tags = split_names(self._input("tags").value)
        genres = split_names(self._input("genres").value)
        sort = self.query_one("#sort", Select).selection
        limit = _number(self._input("limit").value, "How many", 1, 50, 12)
        min_rank = _number(self._input("min-rank").value, "Min tag rank", 0, 100, None)
        if theme is None:
            if not tags and not genres:
                raise ManhwatokError("pick a theme or give at least one tag or genre")
            return SearchQuery(
                tags=tags,
                genres=genres,
                sort=sort or Sort.SCORE,
                limit=limit,
                min_tag_rank=60 if min_rank is None else min_rank,
            )
        if tags or genres:
            raise ManhwatokError("use either a theme or tags/genres, not both")
        query = self.app.ctx.store.themes.get(theme).to_query(limit)
        overrides = {"sort": sort, "min_tag_rank": min_rank}
        return query.model_copy(update={k: v for k, v in overrides.items() if v is not None})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "search":
            event.stop()
            self.search()

    def search(self) -> None:
        try:
            query = self._query()
            account = self._account()
            accent = self._input("accent").value.strip() or None
            if accent is not None:
                check_accent(accent)
        except ManhwatokError as e:
            self.app.fail(e)
            return
        style = {
            "title": self._input("title").value.strip(),
            "hashtags": self._input("hashtags").value.strip() or None,
            "accent": accent,
            "song": self._input("song").value.strip() or None,
        }
        repeats = self.query_one("#repeats", Checkbox).value
        chapters = self.query_one("#chapters", Checkbox).value
        self.query_one("#status", Static).update("searching AniList…")

        def run() -> None:
            ctx, worker = self.app.ctx, get_current_worker()

            def progress(msg: str) -> None:
                if not worker.is_cancelled:
                    self.app.later(self._set_status, msg)

            try:
                results = suggest_for_account(
                    query,
                    account,
                    ctx.metadata,
                    ctx.chapters if chapters else None,
                    ctx.store.history,
                    self.app.clock(),
                    repeats,
                    progress,
                )
            except ManhwatokError as e:
                if worker.is_cancelled:
                    return
                self.app.fail(e)
                return
            if not worker.is_cancelled:
                self.app.call_from_thread(self._found, results, account, style, worker)

        self.run_worker(run, thread=True, group="build-search", exclusive=True)

    def _found(
        self, results: list[Manhwa], account: Account | None, style: dict, worker: Worker
    ) -> None:
        if worker.is_cancelled:
            return  # re-checked on the app thread: cancelled just before this callback ran
        status = self.query_one("#status", Static)
        if not results:
            status.update("no matches — try fewer tags or a lower min tag rank")
            return
        on_build = (
            len(self.app.screen_stack) == 1 and self.app.query_one("#tabs").active == "build"
        )
        if not on_build:
            text = f"{len(results)} candidates — press Search again to pick them"
            status.update(text)
            self.app.notify(text)
            return
        status.update(f"{len(results)} candidates")
        heading = f"New post for {account.display}" if account else "New post"

        def picked(result) -> None:
            if result is None:
                return
            title, items = result

            def save(tools):
                return save_new_post(
                    results,
                    title,
                    items,
                    account,
                    style["hashtags"],
                    style["accent"],
                    style["song"],
                    tools,
                    self.app.clock(),
                )

            if self.app.start_render(save, self._saved):
                status.update("saving and rendering…")

        screen = PicksScreen(heading, style["title"], prefill_items(results), results)
        self.app.push_screen(screen, picked)

    def _saved(self, built) -> None:
        post, slides = built
        self.query_one("#status", Static).update(f"post {post.id} · {len(slides)} slides")
        self.app.notify(f"post {post.id} · {len(slides)} slides")
        self.app.show_post(post.id)

    # --- tag search ----------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "tag-search":
            return
        event.stop()
        if self._tags is None:
            if not self._loading_tags:
                self._load_tags()
        else:
            self._show_tags(event.value)

    def _load_tags(self) -> None:
        self._loading_tags = True

        def run() -> None:
            worker = get_current_worker()
            try:
                tags = self.app.ctx.metadata.list_tags()
            except ManhwatokError as e:
                if not worker.is_cancelled:
                    self.app.fail(e)
                self.app.later(lambda: setattr(self, "_loading_tags", False))
                return
            if not worker.is_cancelled:
                self.app.call_from_thread(self._tags_loaded, tags)
            else:
                self.app.later(lambda: setattr(self, "_loading_tags", False))

        self.run_worker(run, thread=True, group="tag-list", exclusive=True)

    def _tags_loaded(self, tags: list[TagInfo]) -> None:
        self._loading_tags = False
        self._tags = tags
        self._show_tags(self._input("tag-search").value)

    def _show_tags(self, search: str) -> None:
        hits = matching_tags(self._tags or [], search)
        options = self.query_one("#tag-hits", OptionList)
        options.clear_options()
        options.add_options([Option(f"{t.name}  ·  {t.category}", id=t.name) for t in hits])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "tag-hits":
            return
        event.stop()
        tags = self._input("tags")
        tags.value = ", ".join(split_names(f"{tags.value},{event.option.id}"))
        self.app.notify(f"added tag {event.option.id}")
