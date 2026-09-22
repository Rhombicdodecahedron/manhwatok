"""Assisted upload in a real, visible Google Chrome window, driven by Playwright.

Each account gets its own persistent browser profile under `profiles_dir`, where the user logs
in to TikTok by hand once (`manhwatok login`). TikTok never completes a login in a browser that
is being automated, so `login` starts Chrome on its own, with nothing attached to it, and waits
for the user to quit it. `upload` then opens TikTok's upload page in that profile with
Playwright, attaches the slides, types the title and description (picking each hashtag from
TikTok's suggestions), picks a sound, fills in TikTok's own schedule when the post is planned
for later, sets who can see the post when it isn't to go out to everyone, and leaves the window
open: the user reviews the post and clicks Post (or Schedule).
This adapter never clicks Post or Schedule, never sees a password and does
nothing to hide that the browser is automated — no stealth plugins, no extra launch arguments,
no fingerprint, proxy or captcha tricks; it only waits between steps like a person would.
Every TikTok URL and selector lives in `tiktok_page.py`."""

from __future__ import annotations

import random
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from manhwatok.adapters.tiktok_page import TikTokPage
from manhwatok.domain.errors import (
    ManhwatokError,
    NotLoggedIn,
    StorageError,
    UploadUnavailable,
)
from manhwatok.domain.models import Visibility
from manhwatok.domain.plan import schedule_step
from manhwatok.ports.uploader import UploadReport

INSTALL_HINT = "upload needs: uv sync --extra upload"
CHROMIUM_HINT = "upload needs: uv run playwright install chromium"
CHROME_HINT = "upload needs Google Chrome: https://www.google.com/chrome/"
CHROME_PATHS = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",)
CHROME_NAMES = ("google-chrome", "google-chrome-stable")
POLL_MS = 200  # how often to look again for an element that isn't there yet
SCHEDULE_FIX = "set the date and time in the browser yourself"
VISIBILITY_FIX = "choose who can see the post in the browser yourself"


def _load_playwright():
    """(sync_playwright, Error), imported only when a browser is needed, so everything else
    in manhwatok works without the `upload` extra."""
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as e:
        raise UploadUnavailable(INSTALL_HINT) from e
    return sync_playwright, Error


def _find_chrome() -> str | None:
    for path in CHROME_PATHS:
        if Path(path).is_file():
            return path
    for name in CHROME_NAMES:
        if found := shutil.which(name):
            return found
    return None


def _first_line(error: Exception) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


def _forget_cut_short_calls(context) -> None:
    """The Playwright call a Ctrl-C cut short stays pending in Playwright's event loop, and
    asyncio would print "Task was destroyed but it is pending!" about it on the way out. That
    loop is thrown away with Playwright, so it may report nothing. `_loop` isn't public
    Playwright API; without it the only harm is that noise."""
    loop = getattr(context, "_loop", None)
    if loop is not None:
        loop.set_exception_handler(lambda loop, details: None)


class PlaywrightUploader:
    def __init__(
        self,
        profiles_dir: Path,
        debug_dir: Path,
        page: TikTokPage = TikTokPage(),
        pause: tuple[float, float] = (0.5, 1.5),
        type_delay_ms: tuple[float, float] = (20, 60),
        headless: bool = False,
        channel: str | None = "chrome",
        chrome: list[str] | None = None,
    ) -> None:
        """`pause`: seconds to wait between steps, picked at random in that range;
        `type_delay_ms`: the same per typed character. `headless`, `channel` (None: Playwright's
        own Chromium) and `chrome` (the command `login` starts; default: the installed Google
        Chrome) exist for the tests — the commands always open a visible Chrome."""
        self._profiles_dir = profiles_dir
        self._debug_dir = debug_dir
        self._page = page
        self._pause_s = pause
        self._type_delay_ms = type_delay_ms
        self._headless = headless
        self._channel = channel
        self._chrome = chrome
        self._playwright = None
        self._context = None
        self._error: type[Exception] = Exception  # playwright's Error, once it's loaded
        self._interrupted = False  # Ctrl-C while Playwright was at work

    def login(self, handle: str) -> None:
        """Start Chrome on the account's profile at TikTok's login page; returns once the user
        has quit it. Playwright starts Chrome with --use-mock-keychain and --password-store=basic,
        so this one gets them too: otherwise Chrome would lock the saved login (the Mac keychain,
        or the desktop keyring on Linux) with a key the upload's Chrome can't use."""
        _load_playwright()  # a login is only good for uploads, which need the extra
        chrome = self._chrome
        if chrome is None:
            found = _find_chrome()
            if found is None:
                raise UploadUnavailable(CHROME_HINT)
            chrome = [found]
        profile = self._profile(handle)
        args = [
            f"--user-data-dir={profile}",
            "--use-mock-keychain",
            "--password-store=basic",
            "--no-first-run",
            "--no-default-browser-check",
            self._page.login_url,
        ]
        try:
            browser = subprocess.Popen(
                [*chrome, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            raise ManhwatokError(f"could not start Google Chrome for @{handle}: {e}") from e
        try:
            browser.wait()
        except KeyboardInterrupt:
            browser.terminate()
            browser.wait(10)
            raise

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
        with self._noting_ctrl_c():
            return self._upload(
                handle, slides, title, description, sound, debug, schedule_at, visibility
            )

    def close(self) -> None:
        """Best effort, never raises. A Ctrl-C in the terminal also stops Playwright's driver
        (it shares the terminal's process group), so the browser may no longer answer:
        context.close() then fails, or waits forever when the Ctrl-C cut a Playwright call
        short. Stopping Playwright ends the browser either way."""
        context, playwright = self._context, self._playwright
        interrupted, self._interrupted = self._interrupted, False
        self._context = self._playwright = None
        if context is not None:
            if interrupted:
                _forget_cut_short_calls(context)
            else:
                try:
                    context.close()
                except Exception:
                    pass  # the user already closed the browser, or the driver is gone
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass

    # --- steps ---------------------------------------------------------------------------

    @contextmanager
    def _noting_ctrl_c(self):
        """Remember a Ctrl-C on its way out, so close() doesn't wait on the browser."""
        try:
            yield
        except KeyboardInterrupt:
            self._interrupted = True
            raise

    def _upload(
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
        page = self._open(handle)
        problems: list[str] = []
        try:
            self._goto(page, self._page.upload_url)
            file_input = self._upload_input(page, handle)
            if file_input is None:
                problems.append("upload button not found — drag the slides in yourself")
            else:
                self._pause(page)
                problem = self._attach(page, file_input, slides)
                if problem:
                    problems.append(problem)
        except self._error as e:
            self.close()
            raise ManhwatokError(
                f"the browser stopped before the slides were attached: {_first_line(e)}"
            ) from e
        except ManhwatokError:
            self.close()
            raise
        report = UploadReport(attached=not problems, captioned=False, problems=problems)
        if not report.attached:
            problems.append("title and description not typed — paste caption.txt yourself")
        else:
            self._fill_editor(
                page, report, handle, title, description, sound, schedule_at, visibility
            )
        if debug and problems:
            report.debug_dir = self._save_debug(page, slides, problems)
        return report

    def _profile(self, handle: str) -> Path:
        profile = self._profiles_dir / handle
        try:
            profile.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StorageError(f"could not create the browser profile {profile}: {e}") from e
        return profile

    def _open(self, handle: str):
        """Start Chrome on the account's own profile; returns its first tab."""
        self.close()
        sync_playwright, self._error = _load_playwright()
        profile = self._profile(handle)
        try:
            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                profile, channel=self._channel, headless=self._headless, viewport=None
            )
        except self._error as e:
            self.close()
            if "distribution 'chrome' is not found" in str(e):
                raise UploadUnavailable(CHROME_HINT) from e
            if "Executable doesn't exist" in str(e):
                raise UploadUnavailable(CHROMIUM_HINT) from e
            raise ManhwatokError(
                f"could not start the browser for @{handle} (is its window already open?): "
                f"{_first_line(e)}"
            ) from e
        pages = self._context.pages
        return pages[0] if pages else self._context.new_page()

    def _goto(self, page, url: str) -> None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self._page.page_timeout * 1000)
        except self._error as e:
            self.close()
            raise ManhwatokError(f"could not open {url}: {_first_line(e)}") from e

    def _pause(self, page) -> None:
        low, high = self._pause_s
        if high > 0:
            page.wait_for_timeout(random.uniform(low, high) * 1000)

    def _find(self, page, selectors: list[str] | tuple[str, ...], timeout: float, visible=True):
        """The first element matching one of `selectors` (tried in order, in every frame of the
        page), waiting up to `timeout` seconds for one to show up; None if none did. Unless
        `visible` is False, hidden elements don't count."""
        only_visible = " >> visible=true" if visible else ""
        deadline = time.monotonic() + timeout
        while True:
            for selector in selectors:
                for frame in page.frames:
                    element = frame.locator(selector + only_visible).first
                    try:
                        if element.count():
                            return element
                    except self._error:
                        if page.is_closed():
                            raise
                        # the frame went away while we looked; try the next one
            if time.monotonic() >= deadline:
                return None
            page.wait_for_timeout(POLL_MS)

    def _upload_input(self, page, handle: str):
        """The upload page's file input, or None if it doesn't show up in time. Raises
        NotLoggedIn when TikTok sends the browser to its login page instead."""
        deadline = time.monotonic() + self._page.page_timeout
        while True:
            if self._page.login_url_marker in page.url:
                raise NotLoggedIn(f"@{handle} is not logged in — run: manhwatok login @{handle}")
            found = self._find(page, [self._page.file_input], 0, visible=False)
            if found is not None or time.monotonic() >= deadline:
                return found
            page.wait_for_timeout(POLL_MS)

    def _attach(self, page, file_input, slides: list[Path]) -> str | None:
        """None once the slides are attached (in order), else what went wrong."""
        try:
            file_input.set_input_files(slides)
        except self._error as e:
            if page.is_closed():
                raise
            return f"couldn't attach the slides ({_first_line(e)}) — drag them in yourself"
        return None

    def _fill_editor(
        self,
        page,
        report: UploadReport,
        handle,
        title,
        description,
        sound,
        schedule_at=None,
        visibility=Visibility.EVERYONE,
    ) -> None:
        """Title, description, sound, TikTok's own schedule and who can see the post: each step
        that fails is a problem for the user to finish; once the window is gone, the rest is
        skipped."""
        if self._find(page, [self._page.editor_ready], self._page.editor_timeout) is None:
            report.problems.append("the post editor didn't open — check the browser window")
        steps = []
        if title:
            steps.append(("type the title", "type the title yourself", self._title_step))
        steps.append(
            ("type the description", "paste it from caption.txt yourself", self._description_step)
        )
        if sound:
            steps.append(("add the sound", "add one yourself", self._sound_step))
        if schedule_at is not None:
            steps.append(("fill in the schedule", SCHEDULE_FIX, self._schedule_step))
        if visibility is not Visibility.EVERYONE:  # TikTok already opens on Everyone
            steps.append(("choose who can see it", VISIBILITY_FIX, self._visibility_step))
        text = {
            "title": title,
            "description": description,
            "sound": sound,
            "schedule_at": schedule_at,
            "visibility": visibility,
            "handle": handle,
        }
        for what, fix, step in steps:
            try:
                step(page, report, text, fix)
            except self._error as e:
                if page.is_closed():  # e.g. the user closed the window while it was typed in
                    report.problems.append(f"the browser stopped: {_first_line(e)}")
                    return
                # e.g. something lay over a box, so it couldn't be clicked
                report.problems.append(f"couldn't {what} ({_first_line(e)}) — {fix}")

    def _title_step(self, page, report: UploadReport, text: dict, fix: str) -> None:
        box = self._find(page, self._page.title_candidates, self._page.caption_timeout)
        if box is None:
            report.problems.append(f"title box not found — {fix}")
            return
        self._clear(page, box)
        self._type(page, text["title"])
        report.titled = True

    def _description_step(self, page, report: UploadReport, text: dict, fix: str) -> None:
        box = self._find(page, self._page.caption_candidates, self._page.caption_timeout)
        if box is None:
            report.problems.append(f"description box not found — {fix}")
            return
        self._clear(page, box)
        picked = False
        for part in re.split(r"(#[^\s#]+)", text["description"].strip()):
            if picked and part.startswith(" ") and box.inner_text().endswith((" ", "\xa0")):
                part = part[1:]  # TikTok put a space after the hashtag it inserted
            if part:
                self._type(page, part)
            picked = part.startswith("#") and self._pick_hashtag(page, part)
        report.captioned = True

    def _pick_hashtag(self, page, tag: str) -> bool:
        """Pick the hashtag just typed from TikTok's suggestions, so it becomes a real hashtag.
        If TikTok doesn't suggest it, close the list and leave the text as typed."""
        choice = self._find(page, [self._page.hashtag_choice(tag)], self._page.hashtag_timeout)
        if choice is None:
            if self._find(page, [self._page.hashtag_option], 0) is not None:
                page.keyboard.press("Escape")
            return False
        self._pause(page)
        choice.click()
        return True

    def _sound_step(self, page, report: UploadReport, text: dict, fix: str) -> None:
        sound, timeout = text["sound"], self._page.sound_timeout
        button = self._find(page, [self._page.sound_button], self._page.caption_timeout)
        if button is None:
            report.problems.append(f"Add sound button not found — {fix}")
            return
        self._pause(page)
        button.click()
        search = self._find(page, [self._page.sound_search], timeout)
        if search is None:
            report.problems.append(f"sound search not found — {fix}")
            return
        self._clear(page, search)
        self._type(page, sound)
        page.keyboard.press("Enter")
        result = self._find(page, [self._page.sound_result], timeout)
        if result is None:
            report.problems.append(f'no sound found for "{sound}" — {fix}')
            return
        name = result.locator(self._page.sound_result_title).first.inner_text().strip()
        detail = result.locator(self._page.sound_result_detail)
        if detail.count():
            name = f"{name} ({detail.first.inner_text().strip()})"
        self._pause(page)
        result.locator(self._page.sound_use).first.click()
        report.sound = name

    # --- TikTok's own schedule ------------------------------------------------------------

    def _schedule_step(self, page, report: UploadReport, text: dict, fix: str) -> None:
        """Switch TikTok to "Schedule" and fill its date and time in — the user still clicks
        the button. Anything that doesn't work leaves an ordinary "post it now" page and is
        said so, and the report stays unscheduled, so the caller can tell the user."""
        wanted = schedule_step(text["schedule_at"])
        if wanted != text["schedule_at"]:
            report.notes.append(
                f"TikTok schedules on 5 minutes: {text['schedule_at']:%H:%M} → {wanted:%H:%M}"
            )
        if not self._start_scheduling(page, report, text["handle"], fix):
            return
        if not self._pick_time(page, report, wanted, fix):
            return
        if not self._pick_date(page, report, wanted, fix):
            return
        if self._reads_back(page, report, wanted, fix):
            report.scheduled_at = wanted

    def _start_scheduling(self, page, report: UploadReport, handle: str, fix: str) -> bool:
        """Turn the "Schedule" radio on. Only a click on the label's own text moves it: the
        input is covered, and TikTok ignores a forced click on it."""
        radio = self._find(page, [self._page.schedule_radio], self._page.schedule_timeout)
        if radio is None:
            report.problems.append(f"TikTok's Schedule option wasn't there — {fix}")
            return False
        self._pause(page)
        radio.click()
        if self._scheduling(page):
            return True
        report.problems.append(self._consent_problem(page, handle, fix))
        return False

    def _scheduling(self, page) -> bool:
        """Whether the radio really went on, read back from its aria-checked. TikTok takes a
        moment over it, and never moves it at all while its consent modal is up."""
        deadline = time.monotonic() + self._page.schedule_timeout
        while True:
            radio = self._find(page, [self._page.schedule_input], 0, visible=False)
            if radio is not None and radio.get_attribute("aria-checked") == "true":
                return True
            if self._find(page, [self._page.consent_allow], 0) is not None:
                return False  # waiting on the user's consent; it won't move by itself
            if time.monotonic() >= deadline:
                return False
            page.wait_for_timeout(POLL_MS)

    def _consent_problem(self, page, handle: str, fix: str) -> str:
        """What to say when the radio stayed on "Now". The first time an account schedules
        anything, TikTok asks to allow the slides to be saved on its servers ("Allow your video
        to be saved for scheduled posting?") and won't move until Allow is clicked. That is the
        user's call, not manhwatok's: the modal is left open and this says what to do. Asking
        the user instead of telling them is a change to this one method."""
        if self._find(page, [self._page.consent_allow], 0) is not None:
            return (
                f"TikTok asks @{handle} to allow scheduled posting once — it saves the slides "
                "on its servers. Click Allow in the window, then set the time yourself (or "
                "upload again)."
            )
        return f'TikTok stayed on "Now" — {fix}'

    def _pick_time(self, page, report: UploadReport, when: datetime, fix: str) -> bool:
        """The hour, then the minute, each picked from the list the time box opens."""
        page_, timeout = self._page, self._page.schedule_timeout
        box = self._find(page, [page_.time_input], timeout)
        if box is None:
            report.problems.append(f"TikTok's time box wasn't there — {fix}")
            return False
        self._pause(page)
        box.click()
        for which, value in ((0, f"{when:%H}"), (1, f"{when:%M}")):
            option = self._find(page, [page_.time_choice(which, value)], timeout)
            if option is None:
                report.problems.append(f"TikTok's time picker has no {value} — {fix}")
                return False
            self._pause(page)
            option.click()
        page.keyboard.press("Escape")  # close the picker, as a person would
        return True

    def _pick_date(self, page, report: UploadReport, when: datetime, fix: str) -> bool:
        """The day, picked from the calendar the date box opens — only its `valid` cells can
        be picked, and a day number shows once among them (the window is 10 days long)."""
        page_, timeout = self._page, self._page.schedule_timeout
        box = self._find(page, [page_.date_input], timeout)
        if box is None:
            report.problems.append(f"TikTok's date box wasn't there — {fix}")
            return False
        self._pause(page)
        box.click()
        if self._find(page, [page_.calendar], timeout) is None:
            report.problems.append(f"TikTok's calendar didn't open — {fix}")
            return False
        cell = self._find(page, [page_.day_choice(when.day)], 0)
        shown = self._shown_month(page)
        if cell is None and shown != page_.month_title(when):
            # The view holds the next month's first days too, so this is rare; and the window
            # is 10 days, so one step forward is as far as it could ever need to go.
            arrow = self._find(page, [page_.calendar_next], 0)
            if arrow is not None:
                self._pause(page)
                arrow.click()
                cell = self._find(page, [page_.day_choice(when.day)], timeout)
                shown = self._shown_month(page)
        if cell is None:
            report.problems.append(
                f"TikTok's calendar wouldn't take {when:%Y-%m-%d} (it shows {shown}) — {fix}"
            )
            return False
        self._pause(page)
        cell.click()
        return True

    def _shown_month(self, page) -> str:
        """The month the calendar is on, as its header writes it ("September 2026")."""
        month = self._find(page, [self._page.calendar_month], 0)
        year = self._find(page, [self._page.calendar_year], 0)
        if month is None or year is None:
            return "no month"
        return f"{month.inner_text().strip()} {year.inner_text().strip()}"

    def _reads_back(self, page, report: UploadReport, when: datetime, fix: str) -> bool:
        """Both boxes hold what was asked for. They are readonly, so the widgets are the only
        way in: a click that landed elsewhere would otherwise schedule the post for some other
        time without anyone noticing."""
        right = True
        for what, selector, wanted in (
            ("time", self._page.time_input, f"{when:%H:%M}"),
            ("date", self._page.date_input, f"{when:%Y-%m-%d}"),
        ):
            box = self._find(page, [selector], self._page.schedule_timeout)
            got = box.input_value().strip() if box is not None else ""
            if got != wanted:
                report.problems.append(
                    f"TikTok's {what} box reads {got or 'nothing'}, not {wanted} — {fix}"
                )
                right = False
        return right

    # --- who can see the post -------------------------------------------------------------

    def _visibility_step(self, page, report: UploadReport, text: dict, fix: str) -> None:
        """Set TikTok's "Who can see this post". It opens on Everyone, so this only runs for
        another one, and a list already showing it is left alone — there is nothing to click.
        The button's own text is read back afterwards: a click that landed elsewhere would
        otherwise leave the post open to everyone without anyone noticing."""
        wanted, timeout = text["visibility"], self._page.visibility_timeout
        button = self._find(page, [self._page.visibility_trigger], timeout)
        if button is None:
            report.problems.append(f'TikTok\'s "Who can see this post" wasn\'t there — {fix}')
            return
        if self._shown_visibility(button) is wanted:
            report.visibility = wanted
            return
        self._pause(page)
        button.click()
        option = self._find(page, [self._page.visibility_choice(wanted)], timeout)
        label = self._page.visibility_label(wanted)
        if option is None:
            report.problems.append(f'TikTok\'s visibility list has no "{label}" — {fix}')
            return
        self._pause(page)
        option.click()
        self._pause(page)
        shown = button.inner_text().strip()
        report.visibility = self._page.shown_visibility(shown)
        if report.visibility is not wanted:
            report.problems.append(
                f'TikTok\'s "Who can see this post" reads {shown or "nothing"}, not {label} '
                f"— {fix}"
            )

    def _shown_visibility(self, button) -> Visibility | None:
        """Which visibility the button names now, or None for a label manhwatok doesn't know."""
        return self._page.shown_visibility(button.inner_text())

    def _clear(self, page, box) -> None:
        """Click into `box` and empty it: TikTok may prefill it."""
        self._pause(page)
        box.click()
        page.keyboard.press("ControlOrMeta+A")
        page.keyboard.press("Delete")

    def _type(self, page, text: str) -> None:
        low, high = self._type_delay_ms
        for char in text:
            page.keyboard.type(char)
            if high > 0:
                page.wait_for_timeout(random.uniform(low, high))

    def _save_debug(self, page, slides: list[Path], problems: list[str]) -> Path | None:
        """screenshot.png and page.html in <debug_dir>/<post id>-<time>/ (the slides' folder is
        named after the post; upload-<time>/ without slides). Failing to save them is one more
        problem, not an error."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = slides[0].parent.name if slides else "upload"
        folder = self._debug_dir / f"{name}-{stamp}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=folder / "screenshot.png", full_page=True)
            (folder / "page.html").write_text(page.content(), encoding="utf-8")
        except (OSError, self._error) as e:
            problems.append(f"couldn't save the debug files: {_first_line(e)}")
            return None
        return folder
