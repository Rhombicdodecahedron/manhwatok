"""Accounts: filters, style, sounds and saved TikTok login of each account."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from manhwatok.app.accounts import add_account, update_account
from manhwatok.app.login_account import forget_login, login_account, saved_login
from manhwatok.domain.account import MAX_REPEAT_DAYS, Account
from manhwatok.domain.errors import ManhwatokError
from manhwatok.domain.models import ArtSourceName, ArtStyle, Visibility
from manhwatok.domain.text import split_names
from manhwatok.tui.screens.browser import BrowserScreen
from manhwatok.tui.text import clip
from manhwatok.tui.widgets.dialogs import ConfirmModal
from manhwatok.tui.widgets.form import FormModal

LISTS = ("genres", "block_genres", "block_tags")
TEXTS = ("hashtags", "emojis", "default_sound", "accent", "cta_title", "cta_follow")
ART_CHOICES = ", ".join(style.value for style in ArtStyle)
SOURCE_CHOICES = ", ".join(source.value for source in ArtSourceName)
VISIBILITY_CHOICES = ", ".join(who.value for who in Visibility)
LABELS = {
    "genres": "Genres (comma-separated; a title needs one of them; empty = any)",
    "block_genres": "Blocked genres",
    "block_tags": "Blocked tags",
    "hashtags": "Hashtags",
    "emojis": "Emojis after the title on TikTok (\"auto\" = from each post's genres; empty = none)",
    "sounds": (
        "TikTok sounds to pick from when uploading (separate with | ; "
        "a sound can't contain | ; empty = none)"
    ),
    "default_sound": (
        "The sound uploads use without asking (empty = ask which of the sounds above to use)"
    ),
    "accent": "Accent colour",
    "art": f"Slide art for new posts: {ART_CHOICES} (empty = none)",
    "cta_title": "End-slide title (*word* = accent colour)",
    "cta_follow": "End-slide follow line",
    "repeat_days": f"Repeat window in days (1–{MAX_REPEAT_DAYS})",
    "slots": (
        "Posting slots each week, in the time zone (comma-separated <day> HH:MM, day mon..sun "
        "or daily, e.g. mon 19:00, daily 12:30; empty = none)"
    ),
    "rotation": (
        "Rotation: what the posts are about, in turn (comma-separated chapter:<title> or "
        "theme:<name>; a changed rotation starts over from the first)"
    ),
    "timezone": "Time zone of the slots (an IANA name, e.g. Europe/Paris)",
    "art_source": (
        f"Art source for the rotation's list posts: {SOURCE_CHOICES} "
        "(empty = the art style's own)"
    ),
    "visibility": (
        f"Who can see this account's posts: {VISIBILITY_CHOICES} (empty = everyone, which is "
        "TikTok's own default; one post can say otherwise)"
    ),
}


def account_texts(account: Account) -> dict[str, str]:
    """The form's text for each field of `account`."""
    texts = {name: ", ".join(getattr(account, name)) for name in LISTS}
    texts.update({name: getattr(account, name) for name in TEXTS})
    texts["sounds"] = " | ".join(account.sounds)
    texts["art"] = "" if account.art is ArtStyle.NONE else account.art.value
    texts["repeat_days"] = str(account.repeat_days)
    texts["slots"] = ", ".join(account.slots)
    texts["rotation"] = ", ".join(account.rotation)
    texts["timezone"] = account.timezone
    texts["art_source"] = account.art_source.value if account.art_source else ""
    texts["visibility"] = account.visibility.value
    return texts


def _items(text: str) -> list[str]:
    """Comma-separated items, stripped, blanks dropped — repeats kept (a rotation's repeats
    are its own; the account drops repeated slots)."""
    return [item.strip() for item in text.split(",") if item.strip()]


def _art(text: str) -> ArtStyle:
    try:
        return ArtStyle(text.strip().lower() or ArtStyle.NONE)
    except ValueError:
        got = text.strip()
        raise ManhwatokError(f"art must be one of: {ART_CHOICES} — got {got!r}") from None


def _visibility(text: str) -> Visibility:
    try:
        return Visibility(text.strip().lower() or Visibility.EVERYONE)
    except ValueError:
        got = text.strip()
        raise ManhwatokError(
            f"visibility must be one of: {VISIBILITY_CHOICES} — got {got!r}"
        ) from None


def account_fields(texts: dict[str, str], before: dict[str, str] | None) -> dict[str, Any]:
    """Account fields from form text: every filled-in field for a new account (`before` None),
    only the changed ones for an existing account."""
    fields: dict[str, Any] = {}
    for name, text in texts.items():
        if name == "handle":
            continue
        if before is None and not text.strip():
            continue
        if before is not None and text == before[name]:
            continue
        if name in LISTS:
            fields[name] = split_names(text)
        elif name == "sounds":
            fields[name] = [sound.strip() for sound in text.split("|") if sound.strip()]
        elif name == "art":
            fields[name] = _art(text)
        elif name == "visibility":
            fields[name] = _visibility(text)
        elif name == "slots":
            fields[name] = _items(text)
        elif name == "rotation":
            # As `account set --rotation`: a new rotation starts from its first item.
            fields[name] = _items(text)
            fields["rotation_cursor"] = 0
        elif name == "art_source":
            fields[name] = text.strip().lower() or None
        elif name == "repeat_days":
            try:
                fields[name] = int(text)
            except ValueError:
                raise ManhwatokError(
                    f"repeat days must be a whole number from 1 to {MAX_REPEAT_DAYS}"
                ) from None
        else:
            fields[name] = text
    return fields


def _slots_cell(slots: list[str]) -> str:
    if len(slots) > 1:
        return f"{len(slots)} slots"
    return slots[0] if slots else "-"


def _sounds_cell(sounds: list[str]) -> str:
    if len(sounds) > 1:
        return f"{len(sounds)} sounds"
    return clip(sounds[0], 24) if sounds else "-"


class AccountsPane(Vertical):
    DEFAULT_CSS = """
    AccountsPane DataTable { height: 1fr; }
    AccountsPane #accounts-hint { height: 1; color: $text-muted; padding: 0 1; }
    """
    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),  # enter too (a selected row)
        Binding("l", "login", "Log in"),
        Binding("d", "remove", "Remove"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.accounts: dict[str, Account] = {}

    def compose(self) -> ComposeResult:
        yield DataTable(id="accounts-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="accounts-hint")

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(
            "account", "genres", "blocked", "hashtags", "accent", "sounds", "art", "repeat",
            "slots", "login",
        )
        self.reload()

    def focus_main(self) -> None:
        self.query_one(DataTable).focus()

    def refresh_data(self) -> None:
        self.reload()

    def reload(self, select: str | None = None) -> None:
        ctx = self.app.ctx
        keep = select or self.current_handle
        try:
            accounts = ctx.store.accounts.list()
        except ManhwatokError as e:
            self.app.fail(e)
            accounts = []
        self.accounts = {a.handle: a for a in accounts}
        table = self.query_one(DataTable)
        table.clear()
        for a in accounts:
            try:
                login = "saved" if saved_login(ctx.settings.browser_dir, a.handle) else "-"
            except ManhwatokError:
                login = "check"
            table.add_row(
                a.display,
                Text(clip(", ".join(a.genres) or "any", 30)),
                Text(clip(", ".join(a.block_genres + a.block_tags) or "-", 30)),
                Text(clip(a.hashtags or "-", 30)),
                a.accent,
                Text(_sounds_cell(a.sounds)),
                a.art.value,
                f"{a.repeat_days}d",
                _slots_cell(a.slots),
                login,
                key=a.handle,
            )
        if keep in self.accounts:
            table.move_cursor(row=table.get_row_index(keep))
        hint = "" if accounts else "no accounts yet — press a to add one"
        self.query_one("#accounts-hint", Static).update(hint)

    @property
    def current_handle(self) -> str | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    def _selected(self) -> Account | None:
        account = self.accounts.get(self.current_handle or "")
        if account is None:
            self.app.notify("no account selected", severity="warning")
        return account

    def _warn(self, message: str) -> None:
        self.app.notify(message, severity="warning")

    def action_add(self) -> None:
        ctx = self.app.ctx
        defaults = account_texts(Account(handle="new"))
        fields = [("handle", "TikTok handle, e.g. @manhwa.daily", "", "")]
        fields += [(name, LABELS[name], "", defaults[name]) for name in LABELS]

        def save(texts: dict[str, str]) -> Account:
            names = ctx.names(self._warn)
            return add_account(
                ctx.store.accounts, names, texts["handle"], account_fields(texts, None)
            )

        self.app.push_screen(FormModal("Add an account", fields, save), self._saved("added"))

    def action_edit(self) -> None:
        account = self._selected()
        if account is None:
            return
        ctx = self.app.ctx
        for sound in account.sounds:
            if "|" in sound:
                self.app.notify(
                    f"sound {sound!r} contains | — edit it with manhwatok account set --sound",
                    severity="warning",
                )
        before = account_texts(account)
        fields = [(name, LABELS[name], before[name], "") for name in LABELS]

        def save(texts: dict[str, str]) -> Account:
            changes = account_fields(texts, before)
            if not changes:
                return account
            names = ctx.names(self._warn)
            return update_account(ctx.store.accounts, names, account.handle, changes)

        title = f"Edit {account.display}"
        self.app.push_screen(FormModal(title, fields, save), self._saved("saved"))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.action_edit()

    def _saved(self, verb: str):
        def done(account: Account | None) -> None:
            if account is not None:
                self.app.notify(f"{verb} {account.display}")
                self.reload(select=account.handle)

        return done

    def action_login(self) -> None:
        account = self._selected()
        if account is None:
            return
        if self.app.browser_open:
            self.app.notify("a browser is already open — finish there first", severity="warning")
            return
        app, handle = self.app, account.handle

        def job(progress) -> str:
            ctx = app.ctx
            logged = login_account(handle, ctx.store.accounts, ctx.uploader(), progress)
            return f"browser closed — once logged in, uploads post as {logged.display}"

        screen = BrowserScreen(f"Log in {account.display}", job)
        app.push_screen(screen, lambda _: self.reload(select=handle))

    def action_remove(self) -> None:
        account = self._selected()
        if account is None:
            return
        ctx, handle = self.app.ctx, account.handle

        def forget(yes: bool | None) -> None:
            if not yes:
                self.app.notify(f"kept the saved TikTok login for @{handle}")
                return
            try:
                forget_login(ctx.settings.browser_dir, handle)
            except ManhwatokError as e:
                self.app.fail(e)
                return
            self.app.notify(f"deleted the saved TikTok login for @{handle}")

        def remove(yes: bool | None) -> None:
            if not yes:
                return
            try:
                ctx.store.accounts.remove(handle)
                self.app.notify(f"removed @{handle} (its posting history is kept)")
                self.reload()
                profile = saved_login(ctx.settings.browser_dir, handle)
            except ManhwatokError as e:
                self.app.fail(e)
                return
            if profile is not None:
                question = f"Also delete the saved TikTok login for @{handle}?"
                self.app.push_screen(ConfirmModal(question), forget)

        question = f"Remove {account.display}? Its posting history is kept."
        self.app.push_screen(ConfirmModal(question), remove)
