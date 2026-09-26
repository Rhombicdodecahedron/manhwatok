"""Assisted upload on an Android phone: TikTok's own app, driven by Appium (UiAutomator2).

The phone's TikTok app holds the accounts. `login` opens the app with adb alone — nothing
automating it — for the user to log in to (or add) the account by hand, and returns once they
leave the app. `upload` pushes the slides into the phone's gallery (Pictures/manhwatok), makes
sure the app is on the post's account, picks the slides in TikTok's photo picker in order, adds
the sound, types the title and description and sets who can see the post; then it stops on the
app's last screen: the user checks the post on the phone and taps Post. This adapter never taps
Post, never sees a password and does nothing to hide that the phone is automated; it only waits
between steps like a person would. It doesn't fill in a schedule: a scheduled upload says so and
leaves the post to go out when the user taps Post.
Every TikTok app text and selector lives in `tiktok_app.py`."""

from __future__ import annotations

import base64
import random
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from manhwatok.adapters.tiktok_app import TikTokApp
from manhwatok.domain.errors import ManhwatokError, NotLoggedIn, UploadUnavailable
from manhwatok.domain.models import Visibility
from manhwatok.ports.uploader import UploadReport

INSTALL_HINT = "phone upload needs: uv sync --extra phone"
ADB_HINT = "phone upload needs adb (Android platform-tools) on the PATH"
SERVER_HINT = (
    "phone upload needs Appium with its UiAutomator2 driver running at {url} "
    "(npm i -g appium && appium driver install uiautomator2, then: appium)"
)
NO_PHONE_HINT = "no Android phone found — plug it in with USB debugging on (check: adb devices)"
UIAUTOMATOR = "-android uiautomator"  # AppiumBy.ANDROID_UIAUTOMATOR
XPATH = "xpath"
ENTER = 66  # Android's KEYCODE_ENTER
BACK = 4  # KEYCODE_BACK
POLL_S = 0.3  # how often to look again for something that isn't on the screen yet
SLIDES_FIX = "pick the slides yourself from Pictures/manhwatok, in order"
SCHEDULE_PROBLEM = (
    "the phone upload doesn't fill in TikTok's schedule — tap Post at {when:%a %d %b %H:%M} "
    "yourself, or schedule it with the browser upload (MANHWATOK_UPLOADER=browser)"
)
VISIBILITY_FIX = "choose who can see the post on the phone yourself"


def _load_appium():
    """(webdriver.Remote, UiAutomator2Options, WebDriverException), imported only when a phone
    is needed, so everything else in manhwatok works without the `phone` extra."""
    try:
        from appium.options.android import UiAutomator2Options
        from appium.webdriver import Remote
        from selenium.common.exceptions import WebDriverException
    except ImportError as e:
        raise UploadUnavailable(INSTALL_HINT) from e
    return Remote, UiAutomator2Options, WebDriverException


def _first_line(error: Exception) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


def _in_order(elements: list) -> list:
    """Grid cells top to bottom, then left to right, as a person reads them."""
    return sorted(elements, key=lambda e: (e.rect["y"], e.rect["x"]))


class AppiumUploader:
    def __init__(
        self,
        debug_dir: Path,
        server: str = "http://127.0.0.1:4723",
        phone: str = "",
        app: TikTokApp = TikTokApp(),
        pause: tuple[float, float] = (0.5, 1.5),
        push_gap: float = 1.1,
        adb: list[str] | None = None,
    ) -> None:
        """`server`: the Appium server; `phone`: the phone's adb serial ("": the only one
        plugged in). `pause`: seconds to wait between steps, picked at random in that range.
        `push_gap`: seconds between two pushed slides, so the gallery dates them apart and
        lists them in order. `adb` (the command `login` runs; default: adb on the PATH) exists
        for the tests."""
        self._debug_dir = debug_dir
        self._server = server
        self._phone = phone
        self._app = app
        self._pause_s = pause
        self._push_gap = push_gap
        self._adb = adb
        self._driver = None
        self._error: type[Exception] = Exception  # selenium's WebDriverException, once loaded

    # --- login: adb only ---------------------------------------------------------------------

    def login_hint(self, display: str) -> str:
        """What `login` asks of the user, said before the app opens."""
        return (
            f"Log in to {display} in TikTok on the phone (or add it: Profile → your name → "
            "Add account), then go back to the phone's home screen."
        )

    def login(self, handle: str) -> None:
        """Open TikTok on the phone for the user to log in to `handle` (or add it to the
        app's accounts); returns once the app has been on screen and the user has left it."""
        _load_appium()  # a login is only good for uploads, which need the extra
        adb = self._adb_command()
        started = self._run(
            [*adb, "shell", "monkey", "-p", self._app.package,
             "-c", "android.intent.category.LAUNCHER", "1"]
        )
        if "No activities found" in started:
            raise UploadUnavailable(
                f"TikTok ({self._app.package}) isn't installed on the phone — "
                "set MANHWATOK_TIKTOK_APP to its package"
            )
        deadline = time.monotonic() + self._app.launch_timeout
        seen = False
        while True:
            if self._in_front(adb):
                seen = True
            elif seen:
                return
            elif time.monotonic() >= deadline:
                raise ManhwatokError(f"TikTok didn't open on the phone for @{handle}")
            time.sleep(POLL_S)

    def _adb_command(self) -> list[str]:
        if self._adb is not None:
            adb = list(self._adb)
        elif found := shutil.which("adb"):
            adb = [found]
        else:
            raise UploadUnavailable(ADB_HINT)
        return [*adb, "-s", self._phone] if self._phone else adb

    def _run(self, command: list[str]) -> str:
        try:
            done = subprocess.run(
                command, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ManhwatokError(f"adb failed: {e}") from e
        output = done.stdout + done.stderr
        if "no devices" in output or ("not found" in output and "device" in output):
            raise ManhwatokError(NO_PHONE_HINT)
        return output

    def _in_front(self, adb: list[str]) -> bool:
        """Whether TikTok is what the phone shows, from the window that has the focus."""
        for line in self._run([*adb, "shell", "dumpsys", "window"]).splitlines():
            if "mCurrentFocus" in line:
                return f"{self._app.package}/" in line
        return False

    # --- upload ------------------------------------------------------------------------------

    def upload(
        self,
        handle: str,
        slides: list[Path],
        title: str,
        description: str,
        sound: str | None,
        debug: bool,
        schedule_at: datetime | None = None,
        visibility: Visibility = Visibility.EVERYONE,
    ) -> UploadReport:
        self._open()
        problems: list[str] = []
        try:
            self._push(slides)
            self._mobile("activateApp", appId=self._app.package)
            self._on_account(handle)
            problem = self._pick_slides(len(slides))
            if problem:
                problems.append(problem)
        except self._error as e:
            self.close()
            raise ManhwatokError(
                f"the phone stopped before the slides were attached: {_first_line(e)}"
            ) from e
        except ManhwatokError:
            self.close()
            raise
        report = UploadReport(attached=not problems, captioned=False, problems=problems)
        if not report.attached:
            problems.append("title and description not typed — paste caption.txt yourself")
        else:
            self._fill_editor(report, title, description, sound, schedule_at, visibility)
        if debug and problems:
            report.debug_dir = self._save_debug(slides, problems)
        return report

    def close(self) -> None:
        """End the Appium session, best effort; TikTok stays open on the phone for the user."""
        driver, self._driver = self._driver, None
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass  # the server or the phone is already gone

    # --- steps ---------------------------------------------------------------------------

    def _open(self) -> None:
        self.close()
        remote, options_type, self._error = _load_appium()
        options = options_type()
        if self._phone:
            options.udid = self._phone
        options.no_reset = True  # never clear TikTok's data: that is its logins
        options.new_command_timeout = 600
        try:
            self._driver = remote(self._server, options=options)
        except Exception as e:  # the server's down: urllib3's errors, not selenium's
            message = str(e)
            if "connected Android device" in message or "not found in the list" in message:
                raise UploadUnavailable(NO_PHONE_HINT) from e
            if isinstance(e, self._error):
                raise ManhwatokError(f"Appium couldn't start on the phone: {_first_line(e)}") from e
            raise UploadUnavailable(SERVER_HINT.format(url=self._server)) from e

    def _mobile(self, command: str, **args):
        return self._driver.execute_script(f"mobile: {command}", args)

    def _pause(self) -> None:
        low, high = self._pause_s
        if high > 0:
            time.sleep(random.uniform(low, high))

    def _find(self, selectors: list[str] | tuple[str, ...], timeout: float):
        """The first element one of `selectors` (tried in order) finds, waiting up to `timeout`
        seconds for one to show up; None if none did."""
        deadline = time.monotonic() + timeout
        while True:
            for selector in selectors:
                found = self._driver.find_elements(UIAUTOMATOR, selector)
                if found:
                    return found[0]
            if time.monotonic() >= deadline:
                return None
            time.sleep(POLL_S)

    def _tap(self, element) -> None:
        self._pause()
        element.click()

    def _tap_at(self, x: float, y: float) -> None:
        self._pause()
        self._mobile("clickGesture", x=round(x), y=round(y))

    def _push(self, slides: list[Path]) -> None:
        """Copy the slides to the phone, last one first, so the gallery — newest first — lists
        them in order: slide 1 in the top-left cell. Pushing into Pictures puts each one in the
        gallery at once, dated when it arrived; `push_gap` keeps those dates apart. Each name
        is new, so TikTok never picks an older copy of the same post."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = slides[0].parent.name if slides else "upload"
        for n, slide in reversed(list(enumerate(slides, 1))):
            remote = f"{self._app.remote_dir}/{name}-{stamp}-{n:02d}{slide.suffix}"
            try:
                payload = base64.b64encode(slide.read_bytes()).decode("ascii")
            except OSError as e:
                raise ManhwatokError(f"could not read the slide {slide}: {e}") from e
            self._mobile("pushFile", remotePath=remote, payload=payload)
            if n > 1 and self._push_gap > 0:
                time.sleep(self._push_gap)

    def _swipe(self, direction: str) -> None:
        """One swipe over the middle of the screen: "down" scrolls towards the top."""
        size = self._driver.get_window_size()
        self._mobile(
            "swipeGesture",
            left=size["width"] // 10, top=size["height"] // 4,
            width=size["width"] * 8 // 10, height=size["height"] // 2,
            direction=direction, percent=1.0,
        )

    def _profile_top(self):
        """Open the Profile tab scrolled to the top, where the "@handle" is; returns that label,
        or None if it never showed up."""
        app = self._app
        tab = self._find([app.profile_tab], app.switch_timeout)
        if tab is None:
            raise ManhwatokError(
                "couldn't find TikTok's Profile tab on the phone to check the account — "
                "is the app open on its home screen?"
            )
        self._tap(tab)
        for _ in range(3):
            label = self._find([app.any_account_label], app.field_timeout)
            if label is not None:
                return label
            self._swipe("down")
        return None

    def _on_account(self, handle: str) -> None:
        """Make sure the app is on `handle`, switching to it among the app's accounts. Raises
        rather than ever leaving a post on some other account."""
        app = self._app
        label = self._profile_top()
        if label is None:
            raise ManhwatokError(
                "couldn't read which account TikTok is on — open its Profile tab yourself"
            )
        if label.text.strip().lower() == f"@{handle}":
            return
        switcher = self._name_above(label)
        choice = None
        if switcher is not None:
            self._tap(switcher)
            if self._find([app.switch_sheet], app.field_timeout) is not None:
                choice = self._find([app.account_choice(handle)], app.field_timeout)
        if choice is None:
            if switcher is not None:
                self._mobile("pressKey", keycode=BACK)
            raise NotLoggedIn(
                f"@{handle} isn't among the phone's TikTok accounts (it is on "
                f"{label.text.strip()}) — run: manhwatok login @{handle}"
            )
        self._tap(choice)
        deadline = time.monotonic() + app.switch_timeout
        while True:
            label = self._profile_top()
            if label is not None and label.text.strip().lower() == f"@{handle}":
                return
            if time.monotonic() >= deadline:
                raise ManhwatokError(
                    f"TikTok didn't switch to @{handle} — switch to it in the app yourself"
                )
            time.sleep(POLL_S)

    def _name_above(self, label):
        """The account's name: the button with text just above the "@handle", over its middle —
        "Edit" sits beside the name, just as high."""
        top = label.rect["y"]
        middle = label.rect["x"] + label.rect["width"] / 2
        best = None
        for button in self._driver.find_elements(UIAUTOMATOR, self._app.named_button):
            box = button.rect
            bottom = box["y"] + box["height"]
            over = box["x"] <= middle <= box["x"] + box["width"]
            if button.text and over and top - 80 <= bottom <= top + 10:
                if best is None or bottom > best.rect["y"] + best.rect["height"]:
                    best = button
        return best

    def _pick_slides(self, count: int) -> str | None:
        """None once `count` pictures are selected in TikTok's picker and its Next tapped, else
        what went wrong. The pushed slides are the newest pictures: the first `count` cells."""
        app = self._app
        for what, selector in (("Create", app.create_button), ("gallery", app.gallery_button)):
            button = self._find([selector], app.launch_timeout)
            if button is None:
                return f"TikTok's {what} button wasn't there — {SLIDES_FIX}"
            self._tap(button)
        tab = self._find([app.photos_tab], app.field_timeout)
        if tab is not None:  # without it, the picker lists videos and photos together
            self._tap(tab)
        cells = self._cells(count)
        if len(cells) < count:
            return f"TikTok's picker showed {len(cells)} of the {count} slides — {SLIDES_FIX}"
        spot_x, spot_y = app.select_spot
        for cell in cells[:count]:
            box = cell.rect
            self._tap_at(box["x"] + box["width"] * spot_x, box["y"] + box["height"] * spot_y)
        button = self._find([app.picker_next], app.field_timeout)
        if button is None:
            return f"TikTok's Next button wasn't there — {SLIDES_FIX}"
        picked = re.search(r"\((\d+)\)", button.text or "")
        if picked and int(picked.group(1)) != count:
            return (
                f"TikTok says {picked.group(1)} pictures are selected, not {count} — "
                f"{SLIDES_FIX}"
            )
        self._tap(button)
        return None

    def _cells(self, count: int) -> list:
        """The picker's cells in reading order, waiting until at least `count` are there. An
        element's own XPath starts at the element: "/*/*" are its children."""
        deadline = time.monotonic() + self._app.gallery_timeout
        while True:
            grids = self._driver.find_elements(UIAUTOMATOR, self._app.gallery_grid)
            cells = []
            if grids:
                grid = max(grids, key=lambda g: g.rect["width"] * g.rect["height"])
                cells = _in_order(grid.find_elements(XPATH, "/*/*"))
            if len(cells) >= count or time.monotonic() >= deadline:
                return cells
            time.sleep(POLL_S)

    def _fill_editor(
        self,
        report: UploadReport,
        title: str,
        description: str,
        sound: str | None,
        schedule_at: datetime | None,
        visibility: Visibility,
    ) -> None:
        """Sound on the editor, then Next, then title, description and who can see the post on
        the last screen. Each step that fails is a problem for the user to finish; once the
        phone stops answering, the rest is skipped."""
        app = self._app
        if self._find([app.sound_pill, app.editor_next], app.editor_timeout) is None:
            report.problems.append("TikTok's editor didn't open — check the phone")
        steps = []
        if sound:
            steps.append(("add the sound", "add one yourself", self._sound_step))
        else:
            steps.append(("read the sound", "", self._own_sound_step))
        steps.append(("go on to the post screen", "tap Next yourself", self._next_step))
        if title:
            steps.append(("type the title", "type the title yourself", self._title_step))
        steps.append(
            ("type the description", "paste it from caption.txt yourself", self._description_step)
        )
        # Always: the app may open on the last choice this account made.
        steps.append(("choose who can see it", VISIBILITY_FIX, self._visibility_step))
        text = {"title": title, "description": description, "sound": sound,
                "visibility": visibility}
        for what, fix, step in steps:
            try:
                step(report, text, fix)
            except self._error as e:
                if not self._alive():
                    report.problems.append(f"the phone stopped: {_first_line(e)}")
                    return
                report.problems.append(f"couldn't {what} ({_first_line(e)}) — {fix}")
        if schedule_at is not None:
            report.problems.append(SCHEDULE_PROBLEM.format(when=schedule_at.astimezone()))

    def _alive(self) -> bool:
        try:
            self._driver.find_elements(UIAUTOMATOR, "new UiSelector().index(0)")
        except Exception:
            return False
        return True

    def _pill(self) -> str:
        pill = self._find([self._app.sound_pill], self._app.field_timeout)
        return (pill.text or "").strip() if pill is not None else ""

    def _own_sound_step(self, report: UploadReport, text: dict, fix: str) -> None:
        """No sound was asked for, but the app picks one by itself for photos: say which."""
        picked = self._pill()
        if picked and picked.lower() != "add sound":
            report.notes.append(
                f'TikTok added the sound "{picked}" by itself — remove it on the phone if you '
                "want none"
            )

    def _sound_step(self, report: UploadReport, text: dict, fix: str) -> None:
        """Search TikTok's sounds and use the first result. The results have no text to read,
        so what was chosen is read back from the editor afterwards."""
        app, sound = self._app, text["sound"]
        pill = self._find([app.sound_pill], app.field_timeout)
        if pill is None:
            report.problems.append(f"the editor's sound button wasn't there — {fix}")
            return
        self._tap(pill)
        tab = self._find([app.sound_tab], app.sound_timeout)
        icon = self._right_of(tab) if tab is not None else None
        if icon is None:
            report.problems.append(f"sound search not found — {fix}")
            self._mobile("pressKey", keycode=BACK)
            return
        self._tap(icon)
        search = self._find([app.sound_search], app.sound_timeout)
        if search is None:
            report.problems.append(f"sound search not found — {fix}")
            self._back_to_editor()
            return
        self._type(search, sound)
        go = self._find([app.sound_search_go], app.field_timeout)
        if go is not None:
            self._tap(go)
        else:
            self._mobile("pressKey", keycode=ENTER)
        row = self._first_result()
        if row is None:
            report.problems.append(f'no sound found for "{sound}" — {fix}')
            self._back_to_editor()
            return
        box, (spot_x, spot_y) = row.rect, app.use_spot
        self._tap_at(box["x"] + box["width"] * spot_x, box["y"] + box["height"] * spot_y)
        self._back_to_editor()
        report.sound = self._pill() or None
        if report.sound is None:
            report.problems.append(f"couldn't tell which sound TikTok used — {fix}")

    def _right_of(self, anchor):
        """The right-most icon on the same row as `anchor`, to its right."""
        box = anchor.rect
        middle = box["y"] + box["height"] / 2
        best = None
        for icon in self._driver.find_elements(UIAUTOMATOR, self._app.icon_button):
            r = icon.rect
            if r["x"] >= box["x"] + box["width"] and r["y"] <= middle <= r["y"] + r["height"]:
                if best is None or r["x"] > best.rect["x"]:
                    best = icon
        return best

    def _first_result(self):
        """The first row of the search's results: a row of the biggest list that isn't the
        "Videos with related sounds" strip (a list of its own)."""
        app = self._app
        deadline = time.monotonic() + app.sound_timeout
        while True:
            lists = self._driver.find_elements(UIAUTOMATOR, app.results_list)
            if lists:
                results = max(lists, key=lambda e: e.rect["width"] * e.rect["height"])
                for row in results.find_elements(XPATH, "/*/*"):
                    tall = row.rect["height"] >= 100  # not the sliver of a row cut off below
                    if tall and not row.find_elements(UIAUTOMATOR, app.nested_list):
                        return row
            if time.monotonic() >= deadline:
                return None
            time.sleep(POLL_S)

    def _back_to_editor(self) -> None:
        """Back out of the sounds search and sheet until the editor's Next shows again."""
        for _ in range(3):
            self._pause()
            self._mobile("pressKey", keycode=BACK)
            if self._find([self._app.editor_next], self._app.field_timeout) is not None:
                return

    def _next_step(self, report: UploadReport, text: dict, fix: str) -> None:
        app = self._app
        button = self._find([app.editor_next], app.field_timeout)
        if button is None:
            report.problems.append(f"the editor's Next button wasn't there — {fix}")
            return
        self._tap(button)
        if self._find([app.post_ready], app.editor_timeout) is None:
            report.problems.append(f"TikTok's post screen didn't open — {fix}")

    def _title_step(self, report: UploadReport, text: dict, fix: str) -> None:
        box = self._find(self._app.title_candidates, self._app.field_timeout)
        if box is None:
            report.problems.append(f"title box not found — {fix}")
            return
        self._type(box, text["title"])
        report.titled = True

    def _description_step(self, report: UploadReport, text: dict, fix: str) -> None:
        box = self._find(self._app.caption_candidates, self._app.field_timeout)
        if box is None:
            report.problems.append(f"description box not found — {fix}")
            return
        self._type(box, text["description"].strip())
        report.captioned = True

    def _type(self, box, text: str) -> None:
        """Replace what `box` holds with `text`, then put the keyboard away so it covers
        nothing below. TikTok turns typed #hashtags into hashtags by itself."""
        self._tap(box)
        box.clear()
        box.send_keys(text)
        try:
            self._mobile("hideKeyboard")
        except self._error:
            pass  # no keyboard up

    def _visibility_step(self, report: UploadReport, text: dict, fix: str) -> None:
        """Set "Who can see this post", then read the row back: a tap that landed elsewhere
        would otherwise leave the post open to everyone without anyone noticing."""
        app, wanted = self._app, text["visibility"]
        row = self._find([app.visibility_row], app.field_timeout)
        if row is None:
            if wanted is not Visibility.EVERYONE:
                report.problems.append(f'TikTok\'s "Who can see this post" wasn\'t there — {fix}')
            return
        if app.shown_visibility(row.text or "") is wanted:
            report.visibility = wanted
            return
        self._tap(row)
        label = app.visibility_label(wanted)
        option = self._find([app.visibility_choice(wanted)], app.field_timeout)
        if option is not None:
            self._tap(option)
        if self._find([app.visibility_sheet], 0) is not None:
            self._pause()
            self._mobile("pressKey", keycode=BACK)  # the sheet stays up after a choice
        if option is None:
            report.problems.append(f'TikTok\'s visibility list has no "{label}" — {fix}')
            return
        # The row is redrawn as the sheet goes: look until it reads what was picked, or time's up.
        deadline = time.monotonic() + app.field_timeout
        while True:
            row = self._find([app.visibility_row], 0)
            shown = (row.text or "").strip() if row is not None else ""
            report.visibility = app.shown_visibility(shown)
            if report.visibility is wanted or time.monotonic() >= deadline:
                break
            time.sleep(POLL_S)
        if report.visibility is not wanted:
            report.problems.append(
                f'TikTok\'s "Who can see this post" reads {shown or "nothing"}, not {label} '
                f"— {fix}"
            )

    def _save_debug(self, slides: list[Path], problems: list[str]) -> Path | None:
        """screenshot.png and screen.xml (every text and content-desc on the phone's screen)
        in <debug_dir>/<post id>-<time>/. Failing to save them is one more problem."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = slides[0].parent.name if slides else "upload"
        folder = self._debug_dir / f"{name}-{stamp}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self._driver.get_screenshot_as_file(str(folder / "screenshot.png"))
            (folder / "screen.xml").write_text(self._driver.page_source, encoding="utf-8")
        except (OSError, self._error) as e:
            problems.append(f"couldn't save the debug files: {_first_line(e)}")
            return None
        return folder
