"""Everything manhwatok knows about TikTok's website: URLs, selectors and timeouts. This is the
only file with TikTok specifics — when TikTok changes its pages, run
`manhwatok upload <id> --debug` and update these from the saved page.html."""

from __future__ import annotations

import json
from dataclasses import dataclass

from manhwatok.domain.models import Visibility


@dataclass(frozen=True)
class TikTokPage:
    login_url: str = "https://www.tiktok.com/login"
    # The Photos tab: the default Videos tab only takes a single video.
    upload_url: str = "https://www.tiktok.com/tiktokstudio/upload?tab=photo"
    # A logged-out browser gets sent from the upload page to a URL containing this.
    login_url_marker: str = "/login"
    # The upload page's file input (usually hidden) that takes several files at once — never
    # the Videos tab's single-file one.
    file_input: str = "input[type=file][multiple]"
    # The title field above the description, most specific first.
    title_candidates: tuple[str, ...] = (
        'input[placeholder="Add a catchy title"]',
        'input[class*="titleInput"]',
    )
    # Where the description goes, most specific first.
    caption_candidates: tuple[str, ...] = (
        '[class*="caption"] [contenteditable="true"]',
        '[contenteditable="true"]',
        "textarea",
    )
    # Appears once TikTok has taken the files and shows the post editor (never clicked).
    editor_ready: str = '[contenteditable="true"], button[data-e2e="post_video_button"]'
    # One entry of the list TikTok opens while a #hashtag is typed; its text is the hashtag.
    hashtag_option: str = ".hashtag-suggestion-item"
    hashtag_topic: str = ".hash-tag-topic"
    # The Sounds dialog: its button, search box, the search's results and a result's parts.
    sound_button: str = 'button:has-text("Add sound")'
    sound_search: str = 'input[placeholder="Search sounds"]'
    sound_result: str = '[class*="SearchResultList"] [role="listitem"]'
    sound_result_title: str = '[class*="infoBasicTitle"]'
    sound_result_detail: str = '[class*="infoBasicDesc"]'
    sound_use: str = 'button:has-text("Use")'
    # --- "When to post", all inside [data-e2e="schedule_container"] ---
    # The Schedule radio can only be turned on by clicking the label's own text: the input is
    # covered, and React ignores a forced click on it or on the circle around it.
    schedule_radio: str = 'label:has(input[name="postSchedule"][value="schedule"]) span.TUXText'
    # Whether it really went on is read from this input's aria-checked ("true"/"false").
    schedule_input: str = 'input[name="postSchedule"][value="schedule"]'
    # The first time an account schedules a post, TikTok asks to allow the slides to be saved
    # on its servers ("Allow your video to be saved for scheduled posting?") and stays on
    # "Now" until Allow is clicked. manhwatok never clicks it; the user allows it once.
    consent_allow: str = 'button:has-text("Allow")'
    # The two readonly inputs of the picker; they are told apart by their value, the time's
    # being HH:MM and the date's YYYY-MM-DD (in DOM order the time comes first).
    time_input: str = '.scheduled-picker input[value*=":"]'
    date_input: str = '.scheduled-picker input[value*="-"]'
    # The lists the time input opens: hours ("00".."23") then minutes in 5-minute steps.
    time_option_list: str = ".tiktok-timepicker-option-list"
    time_option: str = ".tiktok-timepicker-option-item"
    # The calendar the date input opens: only `valid` days can be picked, the second arrow is
    # the next month, and the title says which month is on show.
    calendar: str = ".calendar-wrapper"
    calendar_day: str = ".calendar-wrapper span.day.valid"
    calendar_month: str = ".calendar-wrapper span.month-title"
    calendar_year: str = ".calendar-wrapper span.year-title"
    calendar_next: str = ".calendar-wrapper span.arrow >> nth=1"
    # The months as TikTok's calendar writes them (TikTok Studio is in English).
    months: tuple[str, ...] = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    # --- "Who can see this post", the list just under "When to post" ---
    visibility_container: str = '[data-e2e="video_visibility_container"]'
    # The button that opens the list; its own text is what is chosen, so it is read back too.
    visibility_trigger: str = '[data-e2e="video_visibility_container"] button[role="combobox"]'
    # The options open in a popup outside the container, so they are looked for on the page.
    # Their data-value is not in display order (Friends is 2, Only you is 1): the visible text
    # says which is which, and `visibility_choice` matches on that.
    visibility_option: str = '[role="listbox"] [role="option"]'
    visibility_option_text: str = "span.TUXText"
    # What TikTok's list calls each Visibility, in its order (TikTok Studio is in English).
    visibility_names: tuple[str, ...] = ("Everyone", "Friends", "Only you")
    page_timeout: float = 30.0  # seconds: load the page, find the file input
    editor_timeout: float = 60.0  # seconds: TikTok processes the files, shows the editor
    caption_timeout: float = 5.0  # seconds: the title/description boxes, once the editor is there
    hashtag_timeout: float = 3.0  # seconds: TikTok suggests a typed hashtag
    sound_timeout: float = 10.0  # seconds: the Sounds dialog opens, a search finds something
    schedule_timeout: float = 5.0  # seconds: the radio turns on, a picker or the calendar opens
    visibility_timeout: float = 5.0  # seconds: the list opens, the trigger reads back

    def hashtag_choice(self, tag: str) -> str:
        """The suggestion that is exactly `tag` (TikTok lists hashtags in lowercase)."""
        return f"{self.hashtag_option}:has({self.hashtag_topic}:text-is({json.dumps(tag.lower())}))"

    def time_choice(self, which: int, value: str) -> str:
        """The option reading exactly `value` in the hours (which=0) or minutes (which=1)
        list. Exact text on purpose: "2" would otherwise match "21" too."""
        return (
            f"{self.time_option_list} >> nth={which} >> "
            f"{self.time_option}:text-is({json.dumps(value)})"
        )

    def day_choice(self, day: int) -> str:
        """The calendar cell for day-of-month `day`, and only if TikTok allows that day. A day
        number shows at most once among the valid ones: the window is 10 days long."""
        return f"{self.calendar_day}:text-is({json.dumps(str(day))})"

    def visibility_label(self, visibility: Visibility) -> str:
        """What TikTok's list calls `visibility`: "Only you" for private."""
        return self.visibility_names[list(Visibility).index(visibility)]

    def shown_visibility(self, text: str) -> Visibility | None:
        """Which visibility a label from the page means, or None for one this doesn't know —
        a TikTok in another language, or an option it has since gained."""
        for visibility, label in zip(Visibility, self.visibility_names):
            if label == text.strip():
                return visibility
        return None

    def visibility_choice(self, visibility: Visibility) -> str:
        """The option reading exactly TikTok's label for `visibility`. The "Friends" option has
        a second line ("Followers you follow back"), so the label is matched on the line of its
        own it sits on, not on the option's whole text."""
        label = json.dumps(self.visibility_label(visibility))
        return f"{self.visibility_option}:has({self.visibility_option_text}:text-is({label}))"

    def month_title(self, when) -> str:
        """The month and year the calendar's header shows for `when`: "September 2026"."""
        return f"{self.months[when.month - 1]} {when:%Y}"
