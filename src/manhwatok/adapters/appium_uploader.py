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
import json
import os
import random
import re
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from manhwatok.adapters.tiktok_app import TikTokApp
from manhwatok.domain.errors import ManhwatokError, NotLoggedIn, UploadUnavailable
from manhwatok.domain.models import Visibility
from manhwatok.ports.uploader import StoryReport, UploadReport

INSTALL_HINT = "phone upload needs: uv sync --extra phone"
ADB_HINT = "phone upload needs adb (Android platform-tools) on the PATH, or ANDROID_HOME set"
SERVER_HINT = (
    "phone upload needs Appium with its UiAutomator2 driver at {url} — install it once "
    "(npm i -g appium && appium driver install uiautomator2); manhwatok starts it by itself"
)
SERVER_FAILED = "Appium didn't start at {url}: {why}"
# Where Android's SDK and a global `appium` usually are when the PATH doesn't say (the app
# may be started from a shell that predates them).
SDK_DIRS = ("~/Android/Sdk", "~/Library/Android/sdk")
APPIUM_PATHS = ("~/.local/share/pnpm/bin/appium", "~/.npm-global/bin/appium")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
SERVER_WAIT_S = 60.0  # seconds for a freshly started Appium to answer
NO_PHONE_HINT = "no Android phone found — plug it in with USB debugging on (check: adb devices)"
UIAUTOMATOR = "-android uiautomator"  # AppiumBy.ANDROID_UIAUTOMATOR
XPATH = "xpath"
ENTER = 66  # Android's KEYCODE_ENTER
BACK = 4  # KEYCODE_BACK
POLL_S = 0.3  # how often to look again for something that isn't on the screen yet
PICK_PAUSE_S = (0.15, 0.4)  # seconds before each picker tap: a person picks faster than they type
REDRAWS = 5  # times a list is read again when the app redraws it mid-read, however late
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


def _android_home() -> str | None:
    """The Android SDK: ANDROID_HOME, ANDROID_SDK_ROOT, else where it usually is."""
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(name):
            return os.environ[name]
    for folder in SDK_DIRS:
        if Path(folder).expanduser().is_dir():
            return str(Path(folder).expanduser())
    return None


def _find_adb() -> str | None:
    if found := shutil.which("adb"):
        return found
    sdk = _android_home()
    adb = Path(sdk) / "platform-tools" / "adb" if sdk else None
    return str(adb) if adb and adb.is_file() else None


def _find_appium() -> str | None:
    if found := shutil.which("appium"):
        return found
    for path in APPIUM_PATHS:
        if Path(path).expanduser().is_file():
            return str(Path(path).expanduser())
    return None


def _first_line(error: Exception) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


def _in_order(elements: list) -> list:
    """Grid cells top to bottom, then left to right, as a person reads them."""
    return sorted(elements, key=lambda e: (e.rect["y"], e.rect["x"]))


def _fills(grid: dict, boxes: list[dict]) -> bool:
    """Whether the cells reach the picker's bottom: there may be more below."""
    return bool(boxes) and max(b["y"] + b["height"] for b in boxes) >= grid["y"] + grid["height"]


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
        appium: list[str] | None = None,
        auto_post: bool = False,
    ) -> None:
        """`server`: the Appium server; `phone`: the phone's adb serial ("": the only one
        plugged in). `pause`: seconds to wait between steps, picked at random in that range.
        `push_gap`: seconds between two pushed slides, so the gallery dates them apart and
        lists them in order. `adb` (the command `login` runs; default: adb on the PATH or in
        the SDK) and `appium` (the server started when none answers at a local `server`;
        default: the installed one, [] for never) exist for the tests. `auto_post`: tap Post
        — and share to the Story — itself once every step went fine."""
        self._debug_dir = debug_dir
        self._server = server
        self._phone = phone
        self._app = app
        self._pause_s = pause
        self._push_gap = push_gap
        self._adb = adb
        self._appium = appium
        self._auto_post = auto_post
        self._server_process: subprocess.Popen | None = None  # the Appium this one started
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
        elif found := _find_adb():
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
            if self._auto_post:
                self._post(report)
        if debug and problems:
            report.debug_dir = self._save_debug(slides, problems)
        return report

    def close(self) -> None:
        """End the Appium session, and the Appium server if this one started it; best effort.
        TikTok stays open on the phone for the user."""
        driver, self._driver = self._driver, None
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass  # the server or the phone is already gone
        server, self._server_process = self._server_process, None
        if server is not None:
            server.terminate()
            try:
                server.wait(10)
            except subprocess.TimeoutExpired:
                server.kill()

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
            try:
                self._driver = remote(self._server, options=options)
            except Exception as e:
                if isinstance(e, self._error) or not self._start_server():
                    raise
                self._driver = remote(self._server, options=options)
        except UploadUnavailable:
            raise
        except Exception as e:  # the server's down: urllib3's errors, not selenium's
            self.close()
            message = str(e)
            if "connected Android device" in message or "not found in the list" in message:
                raise UploadUnavailable(NO_PHONE_HINT) from e
            if isinstance(e, self._error):
                raise ManhwatokError(f"Appium couldn't start on the phone: {_first_line(e)}") from e
            raise UploadUnavailable(SERVER_HINT.format(url=self._server)) from e
        # Don't wait for TikTok to go still before each look (up to 10 s by default): its
        # videos and animations rarely do, and every look polls anyway.
        try:
            self._driver.update_settings({"waitForIdleTimeout": 1000})
        except Exception:
            pass  # an older driver: it waits as it always did


    def _start_server(self) -> bool:
        """Start Appium when `server` is on this computer and nothing answers there; True once
        it answers. False when it's elsewhere or not installed (the caller then says how)."""
        where = urlsplit(self._server)
        command = self._appium
        if command is None:
            found = _find_appium()
            command = [found] if found else []
        if where.hostname not in LOCAL_HOSTS or not command:
            return False
        env = dict(os.environ)
        sdk = _android_home()
        if sdk:
            env.setdefault("ANDROID_HOME", sdk)
            tools = str(Path(sdk) / "platform-tools")
            env["PATH"] = os.pathsep.join([tools, env.get("PATH", "")])
        try:
            self._server_process = subprocess.Popen(
                [*command, "--address", where.hostname, "--port", str(where.port or 4723),
                 "--log-level", "error"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,  # a Ctrl-C in the terminal is for manhwatok to handle
            )
        except OSError as e:
            raise UploadUnavailable(SERVER_FAILED.format(url=self._server, why=e)) from e
        deadline = time.monotonic() + SERVER_WAIT_S
        while True:
            if self._server_process.poll() is not None:
                said = (self._server_process.stderr.read() or b"").decode(errors="replace")
                self._server_process = None
                why = said.strip().splitlines()[-1] if said.strip() else "it stopped at once"
                raise UploadUnavailable(SERVER_FAILED.format(url=self._server, why=why))
            if self._answers():
                return True
            if time.monotonic() >= deadline:
                self.close()
                raise UploadUnavailable(
                    SERVER_FAILED.format(url=self._server, why="no answer in time")
                )
            time.sleep(POLL_S)

    def _answers(self) -> bool:
        try:
            with urllib.request.urlopen(self._server.rstrip("/") + "/status", timeout=2):
                return True
        except OSError:
            return False

    def _mobile(self, command: str, **args):
        return self._driver.execute_script(f"mobile: {command}", args)

    def _pause(self, pause: tuple[float, float] | None = None) -> None:
        low, high = self._pause_s if pause is None else (
            min(pause[0], self._pause_s[0]), min(pause[1], self._pause_s[1])
        )
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

    def _tap_at(self, x: float, y: float, pause: tuple[float, float] | None = None) -> None:
        self._pause(pause)
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

    def _profile_top(self, restart: bool = False):
        """Open the Profile tab scrolled to the top, where the "@handle" is; returns that label,
        or None if it never showed up. With `restart`, TikTok stuck on a screen without its
        tabs (the camera, which Back doesn't leave) is restarted once, on its home screen —
        never once a post is on its way, which that would stop."""
        app = self._app
        tab = self._find([app.profile_tab], app.switch_timeout)
        if tab is None and restart:
            self._mobile("terminateApp", appId=app.package)
            self._mobile("activateApp", appId=app.package)
            tab = self._find([app.profile_tab], app.launch_timeout)
        if tab is None:
            raise ManhwatokError(
                "couldn't find TikTok's Profile tab on the phone to check the account — "
                "is the app open on its home screen, and in English?"
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
        label = self._profile_top(restart=True)
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
        grid, boxes = self._cell_boxes(count)
        already = self._picked_count()
        if already:
            clear = self._find([app.clear_picks], app.field_timeout)
            if clear is not None:
                self._tap(clear)
            if self._picked_count():
                return (
                    f"TikTok's picker already had {already} pictures selected — "
                    "unselect them, then upload again"
                )
        problem = self._select_cells(count, grid, boxes)
        if problem:
            return problem
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

    def _picked_count(self) -> int:
        """How many pictures the picker's Next button says are selected."""
        button = self._find([self._app.picker_next], 0)
        picked = re.search(r"\((\d+)\)", button.text or "") if button is not None else None
        return int(picked.group(1)) if picked else 0

    def _select_cells(self, count: int, grid: dict, boxes: list[dict]) -> str | None:
        """Select the first `count` cells in reading order, one at a time: each tap has to
        take ("Next (n)" counts it) before the next one. The picker moves under the taps — the
        first brings up a tray over its bottom row, one on a cut-off cell scrolls it into view
        — so the circles are read again each time, and the next cell is the one after the
        circle that reads the last pick's number. When that one isn't whole on the screen,
        the picker is scrolled."""
        if len(boxes) < count and not _fills(grid, boxes):  # all there is: the user picks
            return f"TikTok's picker showed {len(boxes)} of the {count} slides — {SLIDES_FIX}"
        picked = scrolls = 0
        circles: list[tuple[dict, str]] = []
        after: int | None = None
        while picked < count:
            # The circles read before the last tap still hold once the tray is up (after the
            # first pick) and nothing moved: the next cell is the one after the last tapped.
            # Reading them all again costs two round trips a circle, so only when needed —
            # after a scroll, or a tap in the bottom row, whose cell may be cut off and so
            # scroll into view.
            if picked < 2 or after is None or after >= len(circles):
                grid, circles = self._circles()
                if picked == 0:
                    after = 0 if circles else None
                else:
                    at = next((n for n, c in enumerate(circles) if c[1] == str(picked)), None)
                    after = None if at is None else at + 1
            if after is None or after >= len(circles):
                if scrolls >= count:
                    return (
                        f"TikTok's picker showed {picked} of the {count} slides — {SLIDES_FIX}"
                    )
                # A slow drag up by half the picker: TikTok's grid ignores scrollGesture
                # down and swipes, and a drag doesn't fling on past the last pick.
                x = grid["x"] + grid["width"] // 2
                start = grid["y"] + grid["height"] * 3 // 4
                self._mobile(
                    "dragGesture", startX=x, startY=start, endX=x,
                    endY=start - grid["height"] // 2, speed=800,
                )
                scrolls += 1
                after = None
                continue
            box = circles[after][0]
            self._tap_at(
                box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, PICK_PAUSE_S
            )
            if not self._picked_becomes(picked + 1):
                return (
                    f"TikTok says {self._picked_count()} pictures are selected, not "
                    f"{picked + 1} — {SLIDES_FIX}"
                )
            picked += 1
            bottom_row = max(b["y"] for b, _ in circles)
            after = None if box["y"] >= bottom_row - 2 else after + 1
        return None

    def _picked_becomes(self, n: int) -> bool:
        deadline = time.monotonic() + self._app.field_timeout
        while self._picked_count() != n:
            if time.monotonic() >= deadline:
                return False
            time.sleep(POLL_S)
        return True

    def _biggest_grid(self):
        """The biggest list on the screen — the picker, or the profile's posts — or None."""
        grids = [
            g for selector in self._app.gallery_grids
            for g in self._driver.find_elements(UIAUTOMATOR, selector)
        ]
        return max(grids, key=lambda g: g.rect["width"] * g.rect["height"], default=None)

    def _circles(self) -> tuple[dict, list[tuple[dict, str]]]:
        """The picker's box, and its cells' selection circles that are whole on the screen, in
        reading order, each with its text: its pick's number, or "". Read again while the
        picker redraws."""
        deadline = time.monotonic() + self._app.gallery_timeout
        while True:
            try:
                found = self._biggest_grid()
                if found is not None:
                    grid = found.rect
                    circles = [
                        (c.rect, (c.text or "").strip())
                        for c in _in_order(found.find_elements(UIAUTOMATOR, self._app.pick_circle))
                    ]
                    # A circle cut off by an edge is narrower one way than the other.
                    whole = max((max(b["width"], b["height"]) for b, _ in circles), default=0)
                    return grid, [
                        (b, t) for b, t in circles
                        if b["width"] >= whole - 2 and b["height"] >= whole - 2
                    ]
            except self._error:
                pass
            if time.monotonic() >= deadline:
                return {"x": 0, "y": 0, "width": 0, "height": 0}, []
            time.sleep(POLL_S)

    def _cell_boxes(self, count: int) -> tuple[dict, list[dict]]:
        """The picker's box and where its cells are, in reading order, waiting until at least
        `count` are there or they fill the picker. An element's own XPath starts at the element:
        "/*/*" are its children. The picker redraws while it loads, which loses the
        cells mid-read: they are read again."""
        deadline = time.monotonic() + self._app.gallery_timeout
        redraws = 0
        while True:
            grid, boxes = {"x": 0, "y": 0, "width": 0, "height": 0}, []
            try:
                found = self._biggest_grid()
                if found is not None:
                    grid = found.rect
                    boxes = [c.rect for c in _in_order(found.find_elements(XPATH, "/*/*"))]
            except self._error:
                redraws += 1
                if redraws <= REDRAWS:
                    time.sleep(POLL_S)
                    continue
            if len(boxes) >= count or _fills(grid, boxes) or time.monotonic() >= deadline:
                return grid, boxes
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
        # The row is redrawn as the sheet goes: look until it reads what was picked, or time's
        # up — and a few times at least, since one look on the phone can come back empty and
        # take the whole window (a wrong "reads nothing" keeps Post from being tapped).
        deadline = time.monotonic() + app.field_timeout
        looks = 0
        while True:
            row = self._find([app.visibility_row], 0)
            shown = (row.text or "").strip() if row is not None else ""
            report.visibility = app.shown_visibility(shown)
            looks += 1
            if report.visibility is wanted or (looks >= 3 and time.monotonic() >= deadline):
                break
            time.sleep(POLL_S)
        if report.visibility is not wanted:
            report.problems.append(
                f'TikTok\'s "Who can see this post" reads {shown or "nothing"}, not {label} '
                f"— {fix}"
            )

    def _post(self, report: UploadReport) -> None:
        """Tap Post — only when nothing is left for the user to finish (a problem, a planned
        time the app can't hold): then it is theirs to post. Posted once the post screen
        goes away."""
        if report.problems:
            report.notes.append("Post not tapped: finish the above on the phone, then tap it")
            return
        app = self._app
        try:
            button = self._find([app.post_ready], app.field_timeout)
            if button is None:
                report.problems.append("TikTok's Post button wasn't there — tap it yourself")
                return
            self._tap(button)
            if self._gone(app.post_ready, app.editor_timeout):
                report.posted = True
            else:
                report.problems.append(
                    "tapped Post, but TikTok stayed on the post screen — check the phone"
                )
        except self._error as e:
            report.problems.append(f"couldn't tap Post ({_first_line(e)}) — check the phone")

    def _gone(self, selector: str, timeout: float) -> bool:
        """Whether `selector` stops finding anything within `timeout` seconds."""
        deadline = time.monotonic() + timeout
        while self._driver.find_elements(UIAUTOMATOR, selector):
            if time.monotonic() >= deadline:
                return False
            time.sleep(POLL_S)
        return True

    # --- the Story ---------------------------------------------------------------------------

    def add_to_story(
        self, handle: str, title: str, debug: bool = False, text: str = ""
    ) -> StoryReport:
        """Once the post is out: open the account's newest post, Share → Add to Story, and
        stop on TikTok's Story screen for the user to share it — or, with `auto_post`, share
        it too. `text` is written on the Story above the post. Never opens a post whose text
        doesn't show `title`, so no other post is ever shared."""
        fix = "add it yourself: open the post → Share → Add to Story"
        report = StoryReport()
        if self._driver is None:
            report.problems.append(f"the phone isn't connected any more — {fix}")
            return report
        app, problems = self._app, report.problems
        if self._find([app.post_ready], 0) is not None:
            problems.append(
                "TikTok is still on the post screen — tap Post first, then add it to your Story "
                "from the post (Share → Add to Story)"
            )
            return report
        try:
            # A post's video keeps the screen busy: don't wait for it to settle before each look.
            self._driver.update_settings({"waitForIdleTimeout": 100})
            self._snap(debug, "story-1-after-post")
            cell = self._newest_post(handle, problems, fix)
            if cell is None:
                return report
            self._tap(cell)
            if not self._shows_title(title):
                self._snap(debug, "story-2-post")
                self._mobile("pressKey", keycode=BACK)
                problems.append(f"the newest post of @{handle} doesn't read \"{title}\" — {fix}")
                return report
            share = self._find([app.share_button], app.field_timeout)
            if share is None:
                self._snap(debug, "story-2-post")
                problems.append(f"TikTok's Share button wasn't there — {fix}")
                return report
            self._tap(share)
            story = self._story_button()
            if story is None:
                self._snap(debug, "story-3-share")
                problems.append(f"TikTok's share sheet has no Add to Story — {fix}")
                return report
            self._tap(story)
            button = self._find([app.story_share], app.editor_timeout)
            if button is not None and text.strip() and not self._story_text(text.strip()):
                problems.append(f'couldn\'t write "{text.strip()}" on the Story — do it yourself')
            self._snap(debug, "story-4-story")
            if button is None:
                problems.append(f"TikTok's Story screen didn't open — {fix}")
            elif problems:
                pass  # the user finishes it: never share a Story that isn't what was asked
            elif self._auto_post:
                self._tap(button)
                if self._gone(app.story_share, app.editor_timeout):
                    report.shared = True
                else:
                    problems.append("tapped Add to Story, but TikTok stayed there — check it")
        except self._error as e:
            problems.append(f"couldn't add it to the Story ({_first_line(e)}) — {fix}")
        return report

    def _story_text(self, text: str) -> bool:
        """Write `text` on the open Story screen with its "Aa" tool and move it above the
        post's card; False if the tool didn't open as expected."""
        app = self._app
        size = self._driver.get_window_size()
        spot_x, spot_y = app.story_text_button_spot
        self._tap_at(size["width"] * spot_x, size["height"] * spot_y)
        box = self._find([app.story_text_box], app.field_timeout)
        done = self._find([app.story_text_done], app.field_timeout)
        if box is None or done is None:
            if box is not None or done is not None:
                self._mobile("pressKey", keycode=BACK)
            return False
        box.send_keys(text)
        self._tap(done)
        written = self._find([app.story_text_box], app.field_timeout)
        if written is None or (written.text or "").strip() != text:
            return False
        box = written.rect
        to_x, to_y = app.story_text_spot
        self._pause()
        self._mobile(
            "dragGesture",
            startX=box["x"] + box["width"] // 2, startY=box["y"] + box["height"] // 2,
            endX=round(size["width"] * to_x), endY=round(size["height"] * to_y), speed=1500,
        )
        return True

    def _newest_post(self, handle: str, problems: list[str], fix: str):
        """The profile's newest post — the first cell that isn't pinned — once TikTok has
        finished posting it; None (and a problem) when it doesn't show up in time."""
        app = self._app
        if self._profile_top() is None:
            problems.append(f"couldn't open @{handle}'s profile — {fix}")
            return None
        tab = self._find([app.videos_tab], app.field_timeout)
        if tab is not None:  # the profile opens on whichever tab was last used
            self._tap(tab)
        deadline = time.monotonic() + app.posting_timeout
        while True:
            try:  # the grid redraws as the post's "45%" goes up: a lost cell is a look again
                grid = self._biggest_grid()
                cells = []
                if grid is not None:
                    cells = [
                        c for c in _in_order(grid.find_elements(XPATH, "/*/*"))
                        if c.find_elements(UIAUTOMATOR, app.post_cell_marker)
                        and not c.find_elements(UIAUTOMATOR, app.pinned_label)
                    ]
                if cells and not cells[0].find_elements(UIAUTOMATOR, app.posting_label):
                    return cells[0]
            except self._error:
                pass
            if time.monotonic() >= deadline:
                problems.append(f"TikTok hadn't finished posting after a while — {fix}")
                return None
            time.sleep(2)

    def _shows_title(self, title: str) -> bool:
        """Whether the open post shows `title` — its words, emojis aside."""
        words = re.sub(r"[^\w' -]+", " ", title).split()
        if not words:
            return True  # nothing to check it by
        start = " ".join(words[:3])
        selector = f"new UiSelector().textContains({json.dumps(start)})"
        return self._find([selector], self._app.field_timeout) is not None

    def _story_button(self):
        """"Add to Story", scrolling the share sheet's second row to it."""
        app = self._app
        for _ in range(4):
            found = self._find([app.add_to_story], 1)
            if found is not None:
                return found
            anchor = self._find([app.share_row_anchor], 0)
            if anchor is None:
                return None
            size = self._driver.get_window_size()
            box = anchor.rect
            self._mobile(
                "swipeGesture", left=size["width"] // 10, top=box["y"],
                width=size["width"] * 8 // 10, height=box["height"], direction="left",
                percent=0.8,
            )
        return None

    def _snap(self, debug: bool, name: str) -> None:
        """With `debug`, keep the screen as <debug_dir>/story-<time>/<name>.xml/.png."""
        if not debug:
            return
        if not hasattr(self, "_story_dir"):
            self._story_dir = self._debug_dir / f"story-{datetime.now():%Y%m%d-%H%M%S}"
        try:
            self._story_dir.mkdir(parents=True, exist_ok=True)
            (self._story_dir / f"{name}.xml").write_text(self._driver.page_source, "utf-8")
            self._driver.get_screenshot_as_file(str(self._story_dir / f"{name}.png"))
        except (OSError, self._error):
            pass

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
