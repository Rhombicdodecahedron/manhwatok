"""AppiumUploader without a phone: a stand-in for Appium's driver shows TikTok's screens (as
read off TikTok 47 on a real phone) as a map of selector to elements, a stand-in for adb the
login."""

import base64
import io
import sys
from datetime import datetime, timezone

import pytest

from manhwatok.adapters import appium_uploader
from manhwatok.adapters.appium_uploader import AppiumUploader
from manhwatok.adapters.tiktok_app import TikTokApp
from manhwatok.domain.errors import ManhwatokError, NotLoggedIn, UploadUnavailable
from manhwatok.domain.models import Visibility

APP = TikTokApp(
    launch_timeout=0, switch_timeout=0, gallery_timeout=0, editor_timeout=0,
    field_timeout=0, sound_timeout=0, posting_timeout=0,
)
BACK = ("pressKey", {"keycode": 4})


class FakeError(Exception):
    """Stands in for selenium's WebDriverException."""


def _box(x, y, width, height) -> dict:
    return {"x": x, "y": y, "width": width, "height": height}


class FakeElement:
    def __init__(self, driver, name, text="", rect=None, children=(), inner=(), on_click=None):
        self.driver = driver
        self.name = name
        self.text = text
        self.rect = rect or _box(0, 0, 100, 100)
        self.children = list(children)
        self.inner = set(inner)  # selectors that find something inside it
        self.on_click = on_click
        self.stale = 0  # how many more reads find it gone, the app having redrawn it

    def click(self):
        self.driver.log.append(("click", self.name))
        if self.on_click:
            self.on_click()

    def clear(self):
        self.text = ""

    def send_keys(self, text):
        self.driver.log.append(("type", self.name, text))
        self.text = text

    def find_elements(self, by, value):
        if self.stale:
            self.stale -= 1
            raise FakeError("Cached elements 'By.xpath: /*/*' do not exist in DOM anymore")
        if by == "xpath":
            assert value == "/*/*"  # an element's own XPath starts at the element itself
            return list(self.children)
        return [self] if value in self.inner else []


class FakeGrid(FakeElement):
    """TikTok's picker: `total` pictures three to a row, 100 by 200, scrolled `offset` down.
    Only what is in view is there — cut off at the edges, like Android's lists. Each cell's
    circle (near its top right) says its place among the picks. A tap on a cut-off cell
    scrolls it into view, as TikTok does."""

    def __init__(self, driver, total, rect):
        super().__init__(driver, "grid", rect=rect)
        self.total = total
        self.offset = 0
        self.picked: list[int] = []
        self.miss = 0  # taps to ignore

    def _top(self, n):
        return self.rect["y"] + (n // 3) * 200 - self.offset

    def _clip(self, x, y, width, height):
        top, bottom = max(y, self.rect["y"]), min(y + height, self.rect["y"] + self.rect["height"])
        return _box(x, top, width, bottom - top) if bottom > top else None

    def find_elements(self, by, value):
        if self.stale:
            self.stale -= 1
            raise FakeError("Cached elements 'By.xpath: /*/*' do not exist in DOM anymore")
        found = []
        for n in range(self.total):
            if by == "xpath":
                box = self._clip((n % 3) * 100, self._top(n), 100, 200)
                text = ""
            else:
                assert value == APP.pick_circle
                box = self._clip((n % 3) * 100 + 73, self._top(n) + 18, 24, 24)
                text = str(self.picked.index(n) + 1) if n in self.picked else ""
            if box:
                found.append(FakeElement(self.driver, f"cell{n}", text=text, rect=box))
        return found[::-1]  # not in reading order

    def tap(self, x, y) -> bool:
        for n in range(self.total):
            left, top = (n % 3) * 100 + 73, self._top(n) + 18
            if left <= x <= left + 24 and top <= y <= top + 24:
                if self.miss:
                    self.miss -= 1
                    return True
                self.picked.remove(n) if n in self.picked else self.picked.append(n)
                cut = self._top(n) + 200 - (self.rect["y"] + self.rect["height"])
                if cut > 0:
                    self.offset += cut
                self.driver.picker_next.text = (
                    f"Next ({len(self.picked)})" if self.picked else "Next"
                )
                return True
        return False


class FakeDriver:
    """The phone: `screen` maps a selector to what it finds. Everything done is in `log`; a
    tap at a point runs what `targets` has for the box it falls in."""

    def __init__(self, handle="reads"):
        self.log: list[tuple] = []
        self.pushed: list[tuple[str, bytes]] = []
        self.quits = 0
        self.screen: dict[str, list[FakeElement]] = {}
        self.targets: list[tuple[dict, object]] = []
        self.page_source = "<hierarchy/>"
        self._home(handle)

    def put(self, selector, name, **kwargs) -> FakeElement:
        element = FakeElement(self, name, **kwargs)
        self.screen.setdefault(selector, []).append(element)
        return element

    def _home(self, handle):
        """TikTok's Profile tab on `handle`, then a picker of five cells (given out of order),
        the editor and the post screen with every box the upload types in."""
        self.put(APP.profile_tab, "profile")
        self.label = self.put(APP.any_account_label, "handle", text=f"@{handle}",
                              rect=_box(379, 616, 322, 45))
        self.name = self.put(APP.named_button, "name", text="Name", rect=_box(311, 541, 458, 66))
        self.put(APP.named_button, "edit", text="Edit", rect=_box(799, 532, 144, 84))
        self.screen[APP.named_button].append(self.label)
        self.put(APP.create_button, "create")
        self.put(APP.gallery_button, "gallery")
        self.put(APP.photos_tab, "photos")
        self.put(APP.gallery_grids[0], "small grid", rect=_box(0, 0, 10, 10))
        self.picker = FakeGrid(self, 5, _box(0, 0, 300, 600))
        self.screen[APP.gallery_grids[0]].append(self.picker)
        self.picker_next = self.put(APP.picker_next, "picker next", text="Next")
        self.pill = self.put(APP.sound_pill, "pill", text="Auto Sound")
        self.put(APP.editor_next, "next", text="Next")
        self.put(APP.post_ready, "post", text="Post")
        self.put(APP.title_candidates[0], "title")
        self.put(APP.caption_candidates[0], "description")
        self.row = self.put(APP.visibility_row, "visibility", text="Everyone can view this post",
                            on_click=lambda: self.put(APP.visibility_sheet, "sheet"))

    def long_picker(self, total):
        """A picker of `total` pictures, two rows in view."""
        grids = self.screen[APP.gallery_grids[0]]
        grids.remove(self.picker)
        self.picker = FakeGrid(self, total, _box(0, 0, 300, 400))
        grids.append(self.picker)

    def sounds(self, found=True):
        """The sounds sheet and its search: the first real result is the second row (the
        first is "Videos with related sounds"), and its ✓ sets the editor's sound."""
        self.put(APP.sound_tab, "recent", rect=_box(701, 1354, 152, 57))
        self.put(APP.icon_button, "search icon", rect=_box(972, 1347, 72, 72))
        self.put(APP.icon_button, "play", rect=_box(930, 1499, 132, 132))  # a row lower
        self.put(APP.sound_search, "search")
        self.put(APP.sound_search_go, "go")
        rows = [
            FakeElement(self, "related", rect=_box(0, 381, 1080, 765), inner=[APP.nested_list]),
            FakeElement(self, "sliver", rect=_box(0, 1100, 1080, 18)),
        ]
        if found:
            rows.append(FakeElement(self, "result", rect=_box(0, 1146, 1080, 246)))
            self.targets.append((rows[-1].rect, lambda: setattr(self.pill, "text", "Lofi")))
        self.put(APP.results_list, "small list", rect=_box(0, 480, 1080, 600))
        self.put(APP.results_list, "results", rect=_box(0, 381, 1080, 2259), children=rows)

    def find_elements(self, by, value):
        assert by == "-android uiautomator"
        return list(self.screen.get(value, []))

    def execute_script(self, script, args):
        name = script.removeprefix("mobile: ")
        if name == "pushFile":
            self.pushed.append((args["remotePath"], base64.b64decode(args["payload"])))
            return
        self.log.append((name, args))
        if name == "dragGesture" and self.picker.total > 5:
            self.picker.offset += int((args["startY"] - args["endY"]) * 0.8)  # a bit short
        if name == "clickGesture" and not self.picker.tap(args["x"], args["y"]):
            for box, action in self.targets:
                inside_x = box["x"] <= args["x"] <= box["x"] + box["width"]
                if inside_x and box["y"] <= args["y"] <= box["y"] + box["height"]:
                    action()
        if (name, args) == BACK:
            self.screen.pop(APP.visibility_sheet, None)

    def update_settings(self, settings):
        self.log.append(("settings", settings))

    def get_window_size(self):
        return {"width": 1080, "height": 2640}

    def get_screenshot_as_file(self, path):
        open(path, "wb").write(b"png")

    def quit(self):
        self.quits += 1


class FakeOptions:
    pass


def _fake(monkeypatch, driver=None, error: Exception | None = None):
    """Appium, connecting to `driver` — or failing with `error`. Returns the connections."""
    connections = []

    def remote(url, options):
        connections.append((url, vars(options)))
        if error:
            raise error
        return driver

    monkeypatch.setattr(
        appium_uploader, "_load_appium", lambda: (remote, FakeOptions, FakeError)
    )
    return connections


def _uploader(tmp_path, **options) -> AppiumUploader:
    """Never starts a real Appium: `appium=[]` unless a test gives a stand-in."""
    options.setdefault("appium", [])
    return AppiumUploader(tmp_path / "debug", app=APP, pause=(0, 0), push_gap=0, **options)


def _slides(tmp_path, count=3):
    folder = tmp_path / "20260926-ab12"
    folder.mkdir(exist_ok=True)
    slides = []
    for n in range(1, count + 1):
        slide = folder / f"{n:02d}.png"
        slide.write_bytes(f"slide {n}".encode())
        slides.append(slide)
    return slides


def _upload(uploader, tmp_path, slides=None, sound=None, debug=False, **kwargs):
    slides = _slides(tmp_path) if slides is None else slides
    return uploader.upload("reads", slides, "My title", "caption #manhwa", sound, debug, **kwargs)


def _clicks(driver) -> list[str]:
    return [entry[1] for entry in driver.log if entry[0] == "click"]


def _taps(driver) -> list[tuple[int, int]]:
    return [(e[1]["x"], e[1]["y"]) for e in driver.log if e[0] == "clickGesture"]


def test_without_the_phone_extra_it_says_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "appium", None)
    monkeypatch.setitem(sys.modules, "appium.options.android", None)
    with pytest.raises(UploadUnavailable) as e:
        _upload(_uploader(tmp_path), tmp_path)
    assert str(e.value) == "phone upload needs: uv sync --extra phone"


def test_without_a_running_appium_it_says_how_to_start_one(tmp_path, monkeypatch):
    _fake(monkeypatch, error=ConnectionRefusedError("Connection refused"))
    with pytest.raises(UploadUnavailable) as e:
        _upload(_uploader(tmp_path, server="http://127.0.0.1:9"), tmp_path)
    assert "UiAutomator2 driver at http://127.0.0.1:9" in str(e.value)


def test_without_a_phone_it_says_to_plug_one_in(tmp_path, monkeypatch):
    _fake(monkeypatch, error=FakeError("Could not find a connected Android device in 20000ms."))
    with pytest.raises(UploadUnavailable) as e:
        _upload(_uploader(tmp_path), tmp_path)
    assert "plug it in with USB debugging on" in str(e.value)


def test_it_connects_to_the_chosen_phone_and_never_resets_the_app(tmp_path, monkeypatch):
    connections = _fake(monkeypatch, FakeDriver())
    _upload(_uploader(tmp_path, server="http://appium:4723", phone="R58M"), tmp_path)
    url, options = connections[0]
    assert url == "http://appium:4723"
    assert options["udid"] == "R58M"
    assert options["no_reset"] is True  # clearing TikTok's data would log every account out


def test_a_full_upload_fills_everything_and_never_taps_post(tmp_path, monkeypatch):
    driver = FakeDriver()
    _fake(monkeypatch, driver)
    uploader = _uploader(tmp_path)
    report = _upload(uploader, tmp_path)
    assert report.problems == []
    assert (report.attached, report.titled, report.captioned) == (True, True, True)
    assert report.visibility is Visibility.EVERYONE
    assert ("type", "title", "My title") in driver.log
    assert ("type", "description", "caption #manhwa") in driver.log
    assert "post" not in _clicks(driver)
    uploader.close()
    uploader.close()
    assert driver.quits == 1
    # TikTok stays open on the phone for the user to tap Post: nothing closes the app.
    assert not [name for name, *_ in driver.log if name in ("terminateApp", "removeApp")]


def test_the_sound_tiktok_picks_by_itself_is_mentioned(tmp_path, monkeypatch):
    _fake(monkeypatch, FakeDriver())
    report = _upload(_uploader(tmp_path), tmp_path)
    assert report.sound is None
    assert report.notes == [
        'TikTok added the sound "Auto Sound" by itself — remove it on the phone if you want none'
    ]


def test_slides_go_to_the_gallery_last_first_so_it_lists_them_in_order(tmp_path, monkeypatch):
    driver = FakeDriver()
    _fake(monkeypatch, driver)
    _upload(_uploader(tmp_path), tmp_path)
    assert [data for _, data in driver.pushed] == [b"slide 3", b"slide 2", b"slide 1"]
    paths = [path for path, _ in driver.pushed]
    assert all(p.startswith("/sdcard/Pictures/manhwatok/20260926-ab12-") for p in paths)
    assert [p[-7:] for p in paths] == ["-03.png", "-02.png", "-01.png"]


def test_the_newest_cells_are_selected_in_reading_order(tmp_path, monkeypatch):
    driver = FakeDriver()
    _fake(monkeypatch, driver)
    _upload(_uploader(tmp_path), tmp_path)
    # Top row left to right, on each cell's selection circle; never the smaller grid.
    assert _taps(driver) == [(85, 30), (185, 30), (285, 30)]
    assert _clicks(driver)[:5] == ["profile", "create", "gallery", "photos", "picker next"]


def test_a_picker_that_redraws_while_read_is_read_again(tmp_path, monkeypatch):
    driver = FakeDriver()
    _fake(monkeypatch, driver)
    driver.picker.stale = 2
    report = _upload(_uploader(tmp_path), tmp_path)
    assert report.attached
    assert _taps(driver) == [(85, 30), (185, 30), (285, 30)]


def test_more_slides_than_the_screen_holds_are_picked_scrolling(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.long_picker(total=20)
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path, slides=_slides(tmp_path, 14))
    assert report.attached, report.problems
    assert driver.picker.picked == list(range(14))


def test_the_last_posts_picks_are_cleared_before_any_tap(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.picker_next.text = "Next (12)"  # TikTok kept the last post's picks

    def clear():
        driver.picker_next.text = "Next"

    driver.put(APP.clear_picks, "clear", on_click=clear)
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path)
    assert report.attached, report.problems
    clicks = _clicks(driver)
    assert clicks.index("clear") < clicks.index("picker next")
    assert _taps(driver)[0] == (85, 30)


def test_picks_that_wont_clear_stop_it_before_any_tap(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.picker_next.text = "Next (12)"
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path)
    assert not report.attached
    assert report.problems[0] == (
        "TikTok's picker already had 12 pictures selected — unselect them, then upload again"
    )
    assert _taps(driver) == []


def test_a_picker_with_fewer_pictures_than_slides_says_so(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.long_picker(total=10)
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path, slides=_slides(tmp_path, 14))
    assert not report.attached
    assert report.problems[0] == (
        "TikTok's picker showed 10 of the 14 slides — pick the slides yourself from "
        "Pictures/manhwatok, in order"
    )


def test_tiktok_stuck_off_its_tabs_is_restarted_once(tmp_path, monkeypatch):
    driver = FakeDriver()
    tab = driver.screen.pop(APP.profile_tab)  # on the camera: Back doesn't leave it
    real = driver.execute_script

    def execute_script(script, args):
        if script == "mobile: terminateApp":
            driver.screen[APP.profile_tab] = tab
        return real(script, args)

    driver.execute_script = execute_script
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path)
    assert report.attached, report.problems
    names = [e[0] for e in driver.log]
    assert names.index("terminateApp") < names.index("activateApp", names.index("terminateApp"))


def test_tiktok_still_off_its_tabs_after_a_restart_is_an_error(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.screen.pop(APP.profile_tab)
    _fake(monkeypatch, driver)
    with pytest.raises(ManhwatokError, match="couldn't find TikTok's Profile tab"):
        _upload(_uploader(tmp_path), tmp_path)
    assert [e[0] for e in driver.log].count("terminateApp") == 1


def test_too_few_cells_is_a_problem_and_nothing_is_typed(tmp_path, monkeypatch):
    driver = FakeDriver()
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path, slides=_slides(tmp_path, 6))
    assert not report.attached
    assert report.problems == [
        "TikTok's picker showed 5 of the 6 slides — pick the slides yourself from "
        "Pictures/manhwatok, in order",
        "title and description not typed — paste caption.txt yourself",
    ]
    assert _taps(driver) == []


def test_a_selection_count_that_disagrees_is_a_problem(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.picker.miss = 1  # a tap TikTok didn't take
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path)
    assert not report.attached
    assert report.problems[0].startswith("TikTok says 0 pictures are selected, not 1")
    assert len(_taps(driver)) == 1  # stopped at the tap that didn't take


def test_it_switches_to_the_posts_account(tmp_path, monkeypatch):
    driver = FakeDriver(handle="other")

    def sheet():
        driver.put(APP.switch_sheet, "switch sheet")
        driver.put(APP.account_choice("reads"), "reads",
                   on_click=lambda: setattr(driver.label, "text", "@reads"))

    driver.name.on_click = sheet
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path)
    assert report.attached
    # The name above the @handle opens the switcher — never "Edit", just as high beside it.
    assert _clicks(driver)[:4] == ["profile", "name", "reads", "profile"]


def test_an_account_the_phone_hasnt_got_is_refused_before_anything_is_picked(
    tmp_path, monkeypatch
):
    driver = FakeDriver(handle="other")
    driver.name.on_click = lambda: driver.put(APP.switch_sheet, "switch sheet")
    _fake(monkeypatch, driver)
    with pytest.raises(NotLoggedIn) as e:
        _upload(_uploader(tmp_path), tmp_path)
    assert str(e.value) == (
        "@reads isn't among the phone's TikTok accounts (it is on @other) — run: manhwatok "
        "login @reads"
    )
    assert BACK in driver.log  # the switcher is closed again
    assert "create" not in _clicks(driver)
    assert driver.quits == 1


def test_the_profile_is_scrolled_up_to_its_handle(tmp_path, monkeypatch):
    driver = FakeDriver()
    label = driver.screen.pop(APP.any_account_label)

    def scrolled(script, args, execute=driver.execute_script):
        execute(script, args)
        if script == "mobile: swipeGesture":
            driver.screen[APP.any_account_label] = label

    driver.execute_script = scrolled
    _fake(monkeypatch, driver)
    assert _upload(_uploader(tmp_path), tmp_path).attached
    assert [e[1]["direction"] for e in driver.log if e[0] == "swipeGesture"] == ["down"]


def test_the_phone_going_away_before_the_slides_are_in_is_an_error(tmp_path, monkeypatch):
    driver = FakeDriver()

    def gone(selector, value):
        raise FakeError("socket hang up\nstack")

    driver.find_elements = gone
    _fake(monkeypatch, driver)
    with pytest.raises(ManhwatokError) as e:
        _upload(_uploader(tmp_path), tmp_path)
    assert str(e.value) == "the phone stopped before the slides were attached: socket hang up"
    assert driver.quits == 1


def test_the_sound_is_searched_and_the_first_result_used(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.sounds()
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path, sound="Lofi Beats")
    assert report.problems == []
    assert report.sound == "Lofi"  # read back from the editor: the results have no text
    assert ("type", "search", "Lofi Beats") in driver.log
    clicks = _clicks(driver)
    # The search is the icon right of the tabs, not the one on the row below.
    assert clicks[clicks.index("pill"):][:3] == ["pill", "search icon", "search"]
    assert "play" not in clicks
    # ✓ on the first real result: past the related videos and the cut-off sliver.
    assert _taps(driver)[-1] == (940, 1269)
    # The sound goes on in the editor, before its Next leads on to the title.
    assert clicks.index("go") < clicks.index("next") < clicks.index("title")


def test_a_sound_it_cant_find_is_a_problem_but_the_rest_goes_on(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.sounds(found=False)
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path, sound="Nothing")
    assert report.problems == ['no sound found for "Nothing" — add one yourself']
    assert report.sound is None and report.captioned


def test_a_missing_description_box_is_a_problem(tmp_path, monkeypatch):
    driver = FakeDriver()
    for selector in APP.caption_candidates:
        driver.screen.pop(selector, None)
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path)
    assert report.problems == [
        "description box not found — paste it from caption.txt yourself"
    ]
    assert report.attached and not report.captioned


def test_the_visibility_is_chosen_read_back_and_its_sheet_closed(tmp_path, monkeypatch):
    driver = FakeDriver()

    def chosen():
        driver.row.text = "Only you can view this post"

    driver.put(APP.visibility_choice(Visibility.PRIVATE), "only you", on_click=chosen)
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path, visibility=Visibility.PRIVATE)
    assert report.problems == []
    assert report.visibility is Visibility.PRIVATE
    assert _clicks(driver)[-2:] == ["visibility", "only you"]
    assert driver.log[-1] == BACK  # the sheet stays up after a choice
    assert APP.visibility_sheet not in driver.screen


def test_the_row_is_never_the_sheets_title():
    import re

    pattern = re.search(r'textMatches\("(.*)"\)', APP.visibility_row).group(1)
    assert re.fullmatch(pattern, "Friends can view this post")
    assert not re.fullmatch(pattern, "Who can view this post")


def test_a_visibility_that_didnt_take_is_a_problem(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.put(APP.visibility_choice(Visibility.FRIENDS), "friends")
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path, visibility=Visibility.FRIENDS)
    assert report.visibility is Visibility.EVERYONE
    assert report.problems == [
        'TikTok\'s "Who can see this post" reads Everyone can view this post, not Friends '
        "— choose who can see the post on the phone yourself"
    ]


def test_a_schedule_is_left_to_the_user(tmp_path, monkeypatch):
    _fake(monkeypatch, FakeDriver())
    when = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
    report = _upload(_uploader(tmp_path), tmp_path, schedule_at=when)
    assert report.scheduled_at is None  # upload_post then says nothing is scheduled
    assert len(report.problems) == 1
    assert "doesn't fill in TikTok's schedule" in report.problems[0]


def test_debug_saves_the_screen_when_something_is_missing(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.screen.pop(APP.post_ready)
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path, debug=True)
    assert report.debug_dir is not None
    assert report.debug_dir.name.startswith("20260926-ab12-")
    assert (report.debug_dir / "screen.xml").read_text() == "<hierarchy/>"
    assert (report.debug_dir / "screenshot.png").is_file()


def test_close_is_safe_without_a_phone_and_after_it_is_gone(tmp_path, monkeypatch):
    uploader = _uploader(tmp_path)
    uploader.close()
    driver = FakeDriver()

    def broken():
        raise FakeError("session gone")

    driver.quit = broken
    _fake(monkeypatch, driver)
    _upload(uploader, tmp_path)
    uploader.close()
    uploader.close()


def test_auto_post_taps_post_once_all_went_fine(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.screen[APP.post_ready][0].on_click = lambda: driver.screen.pop(APP.post_ready)
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path, auto_post=True), tmp_path)
    assert report.posted and report.problems == []
    assert _clicks(driver)[-1] == "post"


def test_without_auto_post_post_is_never_tapped(tmp_path, monkeypatch):
    driver = FakeDriver()
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path), tmp_path)
    assert not report.posted and "post" not in _clicks(driver)


@pytest.mark.parametrize("planned", [False, True])
def test_auto_post_leaves_anything_unfinished_or_planned_to_the_user(
    tmp_path, monkeypatch, planned
):
    driver = FakeDriver()
    if not planned:
        for selector in APP.caption_candidates:
            driver.screen.pop(selector, None)  # the description couldn't be typed
    _fake(monkeypatch, driver)
    when = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc) if planned else None
    report = _upload(_uploader(tmp_path, auto_post=True), tmp_path, schedule_at=when)
    assert not report.posted and "post" not in _clicks(driver)
    assert report.notes[-1].startswith("Post not tapped")


def test_auto_post_that_tiktok_doesnt_take_is_a_problem(tmp_path, monkeypatch):
    _fake(monkeypatch, FakeDriver())  # the post screen stays after the tap
    report = _upload(_uploader(tmp_path, auto_post=True), tmp_path)
    assert not report.posted
    assert report.problems == [
        "tapped Post, but TikTok stayed on the post screen — check the phone"
    ]


def _profile(driver, title="My title"):
    """The profile after posting: a banner, a pinned post, then the new post, whose page
    shows `title`; its Share → Add to Story opens the Story screen."""
    driver.screen.pop(APP.post_ready, None)  # posted: the post screen is gone
    marker = [APP.post_cell_marker]
    banner = FakeElement(driver, "banner", rect=_box(0, 100, 1080, 90))
    pinned = FakeElement(driver, "pinned", rect=_box(0, 200, 358, 477),
                         inner=marker + [APP.pinned_label])
    newest = FakeElement(driver, "newest", rect=_box(361, 200, 358, 477), inner=marker)

    def opened():
        driver.put(f"new UiSelector().textContains(\"{title}\")", "title text")
        driver.put(APP.share_button, "share", on_click=lambda: driver.put(
            APP.add_to_story, "sheet story", on_click=lambda: driver.put(
                APP.story_share, "story share",
                on_click=lambda: driver.screen.pop(APP.story_share))))

    newest.on_click = opened
    driver.screen[APP.gallery_grids[0]] = [
        FakeElement(driver, "grid", rect=_box(0, 100, 1080, 2000),
                    children=[banner, newest, pinned])
    ]
    driver.put(APP.videos_tab, "videos")


def _story(tmp_path, monkeypatch, driver, **options):
    _fake(monkeypatch, driver)
    uploader = _uploader(tmp_path, **options)
    uploader._open()
    return uploader.add_to_story("reads", "My title 💗", debug=False)


def test_the_new_post_is_taken_to_the_story_screen_for_the_user(tmp_path, monkeypatch):
    driver = FakeDriver()
    _profile(driver)
    story = _story(tmp_path, monkeypatch, driver)
    assert (story.shared, story.problems) == (False, [])
    # Never the banner, never the pinned post; the Story screen is left for the user.
    assert _clicks(driver) == ["profile", "videos", "newest", "share", "sheet story"]


def test_with_auto_post_the_story_is_shared_too(tmp_path, monkeypatch):
    driver = FakeDriver()
    _profile(driver)
    story = _story(tmp_path, monkeypatch, driver, auto_post=True)
    assert story.shared and _clicks(driver)[-1] == "story share"


def _text_tool(driver, takes=True):
    """The Story screen's "Aa": a tap at its spot opens a text box and Done; Done leaves the
    typed text on the Story (or, when it doesn't `take`, nothing)."""

    def opened():
        box = driver.put(APP.story_text_box, "text box", rect=_box(0, 1127, 1080, 259))

        def done():
            if not takes:
                driver.screen.pop(APP.story_text_box)
            driver.screen.pop(APP.story_text_done)

        driver.put(APP.story_text_done, "done", on_click=done)
        return box

    driver.targets.append((_box(950, 560, 90, 80), opened))


def test_the_story_gets_its_text_above_the_post(tmp_path, monkeypatch):
    driver = FakeDriver()
    _profile(driver)
    _text_tool(driver)
    _fake(monkeypatch, driver)
    uploader = _uploader(tmp_path, auto_post=True)
    uploader._open()
    story = uploader.add_to_story("reads", "My title 💗", text="new post, check it out !!")
    assert story.shared and story.problems == []
    assert ("type", "text box", "new post, check it out !!") in driver.log
    assert _taps(driver)[-1] == (996, 597)  # the "Aa" tool, at its place on the screen
    [drag] = [e[1] for e in driver.log if e[0] == "dragGesture"]
    assert (drag["startY"], drag["endX"], drag["endY"]) == (1256, 540, 449)
    # Written first, then shared.
    clicks = _clicks(driver)
    assert clicks.index("done") < clicks.index("story share")


def test_a_story_whose_text_didnt_take_is_left_to_the_user(tmp_path, monkeypatch):
    driver = FakeDriver()
    _profile(driver)
    _text_tool(driver, takes=False)
    _fake(monkeypatch, driver)
    uploader = _uploader(tmp_path, auto_post=True)
    uploader._open()
    story = uploader.add_to_story("reads", "My title", text="new post")
    assert not story.shared
    assert story.problems == ['couldn\'t write "new post" on the Story — do it yourself']
    assert "story share" not in _clicks(driver)


def test_a_newest_post_that_isnt_this_one_is_never_shared(tmp_path, monkeypatch):
    driver = FakeDriver()
    _profile(driver, title="Another post")
    story = _story(tmp_path, monkeypatch, driver, auto_post=True)
    assert not story.shared
    assert story.problems[0].startswith("the newest post of @reads doesn't read")
    assert "share" not in _clicks(driver)


# A stand-in for the `appium` command: answers GET /status on the --port it is given, or — with
# FAIL set — says why it can't start and quits, as Appium does without its driver.
FAKE_APPIUM = """
import http.server, os, sys
if os.environ.get("FAIL"):
    sys.stderr.write("Error: Could not find a driver for automationName 'UiAutomator2'\\n")
    sys.exit(1)
port = int(sys.argv[sys.argv.index("--port") + 1])
class Status(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/status" else 404)
        self.end_headers()
    def log_message(self, *args):
        pass
http.server.HTTPServer(("127.0.0.1", port), Status).serve_forever()
"""


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _down_then(driver):
    """Appium's connect: refused until a server is started, then `driver`."""
    calls = []

    def remote(url, options):
        calls.append(url)
        if len(calls) == 1:
            raise ConnectionRefusedError("Connection refused")
        return driver

    return remote, calls


def test_a_local_appium_that_isnt_running_is_started_and_stopped_again(tmp_path, monkeypatch):
    driver = FakeDriver()
    remote, calls = _down_then(driver)
    monkeypatch.setattr(appium_uploader, "_load_appium", lambda: (remote, FakeOptions, FakeError))
    url = f"http://127.0.0.1:{_free_port()}"
    uploader = _uploader(tmp_path, server=url, appium=[sys.executable, "-c", FAKE_APPIUM])
    assert _upload(uploader, tmp_path).attached
    server = uploader._server_process
    assert calls == [url, url] and server.poll() is None
    uploader.close()
    assert server.poll() is not None  # stopped with the upload
    assert driver.quits == 1


def test_an_appium_that_cant_start_says_why(tmp_path, monkeypatch):
    remote, _ = _down_then(FakeDriver())
    monkeypatch.setattr(appium_uploader, "_load_appium", lambda: (remote, FakeOptions, FakeError))
    monkeypatch.setenv("FAIL", "1")
    uploader = _uploader(tmp_path, server=f"http://127.0.0.1:{_free_port()}",
                         appium=[sys.executable, "-c", FAKE_APPIUM])
    with pytest.raises(UploadUnavailable) as e:
        _upload(uploader, tmp_path)
    assert str(e.value).endswith("Could not find a driver for automationName 'UiAutomator2'")
    assert uploader._server_process is None


def test_an_appium_on_another_computer_is_never_started(tmp_path, monkeypatch):
    _fake(monkeypatch, error=ConnectionRefusedError("Connection refused"))
    uploader = _uploader(tmp_path, server="http://10.0.0.9:4723",
                         appium=[sys.executable, "-c", "raise SystemExit('started')"])
    with pytest.raises(UploadUnavailable) as e:
        _upload(uploader, tmp_path)
    assert "at http://10.0.0.9:4723" in str(e.value)
    assert uploader._server_process is None


def test_adb_and_appium_are_found_off_the_path(tmp_path, monkeypatch):
    sdk = tmp_path / "sdk"
    (sdk / "platform-tools").mkdir(parents=True)
    (sdk / "platform-tools" / "adb").write_text("")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("ANDROID_HOME", str(sdk))
    monkeypatch.setattr(appium_uploader, "APPIUM_PATHS", (str(sdk / "platform-tools" / "adb"),))
    assert appium_uploader._find_adb() == str(sdk / "platform-tools" / "adb")
    assert appium_uploader._find_appium() == str(sdk / "platform-tools" / "adb")


# login() uses adb alone: nothing automates TikTok while the user logs in. This stand-in adb
# writes down its arguments and reports TikTok in front for `front` calls, then the launcher.
FAKE_ADB = """
import json, pathlib, sys
log = pathlib.Path(sys.argv[1])
calls = json.loads(log.read_text()) if log.exists() else []
calls.append(sys.argv[3:])
log.write_text(json.dumps(calls))
if sys.argv[3:5] == ["shell", "dumpsys"] or sys.argv[5:7] == ["shell", "dumpsys"]:
    seen = sum(1 for c in calls if "dumpsys" in c)
    app = "com.zhiliaoapp.musically" if seen <= int(sys.argv[2]) else "com.android.launcher3"
    print("  mCurrentFocus=Window{1 u0 " + app + "/.Main}")
elif "{missing}" == "yes":
    print("** No activities found to run, monkey aborted.")
"""


def _fake_adb(tmp_path, front=2, missing=False) -> list[str]:
    script = FAKE_ADB.replace("{missing}", "yes" if missing else "no")
    return [sys.executable, "-c", script, str(tmp_path / "adb.json"), str(front)]


def test_login_opens_tiktok_with_adb_and_waits_until_the_user_leaves_it(tmp_path, monkeypatch):
    import json

    _fake(monkeypatch)
    monkeypatch.setattr(appium_uploader, "POLL_S", 0)
    uploader = _uploader(tmp_path, phone="R58M", adb=_fake_adb(tmp_path, front=2))
    uploader.login("reads")
    calls = json.loads((tmp_path / "adb.json").read_text())
    assert calls[0] == [
        "-s", "R58M", "shell", "monkey", "-p", "com.zhiliaoapp.musically",
        "-c", "android.intent.category.LAUNCHER", "1",
    ]
    assert len(calls) == 1 + 3  # TikTok in front twice, then the home screen


def test_login_says_when_tiktok_isnt_on_the_phone(tmp_path, monkeypatch):
    _fake(monkeypatch)
    with pytest.raises(UploadUnavailable) as e:
        _uploader(tmp_path, adb=_fake_adb(tmp_path, missing=True)).login("reads")
    assert "isn't installed on the phone" in str(e.value)


def test_login_hint_says_where_to_log_in(tmp_path):
    assert "in TikTok on the phone" in _uploader(tmp_path).login_hint("@reads")


def test_manhwatok_uploader_picks_the_phone_or_the_browser(tmp_path):
    from manhwatok.adapters.playwright_uploader import PlaywrightUploader
    from manhwatok.app.container import build_uploader
    from manhwatok.config import Settings

    phone = build_uploader(Settings(data_dir=tmp_path, uploader="phone", tiktok_app="com.ss.x"))
    assert isinstance(phone, AppiumUploader)
    assert phone._app.package == "com.ss.x"
    assert isinstance(build_uploader(Settings(data_dir=tmp_path)), PlaywrightUploader)
    with pytest.raises(ManhwatokError) as e:
        build_uploader(Settings(data_dir=tmp_path, uploader="fax"))
    assert str(e.value) == "MANHWATOK_UPLOADER is 'fax' — use one of: browser, phone"


def test_a_visibility_row_slow_to_redraw_is_read_again_before_giving_up(tmp_path, monkeypatch):
    """On the phone the first look after the sheet closes can come back empty (and slow): the
    row is read again rather than reported as reading nothing, which kept Post from being tapped."""
    driver = FakeDriver()
    row = driver.row
    looks = {"n": 0}
    find = driver.find_elements

    def slow_row(by, value):
        if value == APP.visibility_row and row.text.startswith("Only you"):
            looks["n"] += 1
            if looks["n"] == 1:
                return []  # mid-redraw
        return find(by, value)

    driver.find_elements = slow_row
    driver.put(APP.visibility_choice(Visibility.PRIVATE), "only you",
               on_click=lambda: setattr(row, "text", "Only you can view this post"))
    driver.screen[APP.post_ready][0].on_click = lambda: driver.screen.pop(APP.post_ready)
    _fake(monkeypatch, driver)
    report = _upload(_uploader(tmp_path, auto_post=True), tmp_path, visibility=Visibility.PRIVATE)
    assert report.problems == [] and report.visibility is Visibility.PRIVATE
    assert report.posted


def test_the_session_doesnt_wait_for_tiktok_to_go_still(tmp_path, monkeypatch):
    driver = FakeDriver()
    _fake(monkeypatch, driver)
    _upload(_uploader(tmp_path), tmp_path)
    assert ("settings", {"waitForIdleTimeout": 1000}) in driver.log


def test_the_story_says_when_the_post_isnt_out_yet(tmp_path, monkeypatch):
    driver = FakeDriver()  # still on the post screen: its Post button is there
    _fake(monkeypatch, driver)
    uploader = _uploader(tmp_path)
    uploader._open()
    story = uploader.add_to_story("reads", "My title")
    assert story.problems == [
        "TikTok is still on the post screen — tap Post first, then add it to your Story from "
        "the post (Share → Add to Story)"
    ]


def test_selector_patterns_have_no_backslash_the_phone_would_take_literally():
    """UiAutomator on the phone reads a backslash in a textMatches pattern as a backslash:
    "Only\\ you" never matched the row, which kept Post from being tapped."""
    import re

    for selector, texts in (
        (APP.visibility_row, ["Only you can view this post", "Friends can view this post"]),
        (APP.account_choice("your.real.handle"), ["@your.real.handle", "YOUR.REAL.HANDLE"]),
    ):
        assert "\\" not in selector
        pattern = re.search(r'Matches\("(.*)"\)', selector).group(1)
        assert all(re.fullmatch(pattern, t) for t in texts)
    choice = re.search(r'Matches\("(.*)"\)', APP.account_choice("a.b")).group(1)
    assert not re.fullmatch(choice, "axb")
