"""Everything manhwatok knows about TikTok's Android app: its package, the words, descriptions
and resource ids on its screens (as UiAutomator selectors), where to tap on the parts it draws
without any, and timeouts. This is the only file with TikTok app specifics — when the app
changes, run `manhwatok upload <id> --debug` with the phone upload and update these from the
saved screen.xml (Appium's page source: every text, content-desc and id on the screen). The app
has to be in English, like TikTok Studio for the browser upload.

Read off TikTok 47.0.3 on Android 16 (September 2026). Most of the app's resource ids are
obfuscated and change with each version (`id/l34`), so they are only used where they read as
words (`id/upload_hot_area`)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from manhwatok.domain.models import Visibility


def _q(text: str) -> str:
    """`text` as a UiSelector string argument."""
    return json.dumps(text)


def _id(name: str) -> str:
    """The element with resource id `name`, whatever the app's package."""
    return f"new UiSelector().resourceIdMatches({_q('.*:id/' + name)})"


@dataclass(frozen=True)
class TikTokApp:
    # The global app; some regions have com.ss.android.ugc.trill (MANHWATOK_TIKTOK_APP).
    package: str = "com.zhiliaoapp.musically"
    # Where the slides are pushed on the phone; pushing a picture there also puts it in the
    # phone's gallery, so TikTok's picker lists it.
    remote_dir: str = "/sdcard/Pictures/manhwatok"
    # --- which account the app is on ---
    profile_tab: str = 'new UiSelector().description("Profile")'
    # The Profile tab's "@handle" under the account's name; only there when scrolled to the top.
    any_account_label: str = 'new UiSelector().className("android.widget.Button").textStartsWith("@")'
    # Candidates for the account's name, the button that opens "Switch account": the one just
    # above the "@handle" is it (the name has a ▾ after it, but no text of its own to say so).
    named_button: str = 'new UiSelector().className("android.widget.Button").clickable(true)'
    switch_sheet: str = 'new UiSelector().text("Switch account")'
    # --- choosing the slides ---
    create_button: str = 'new UiSelector().description("Create")'
    # The gallery thumbnail beside the camera's shutter.
    gallery_button: str = _id("upload_hot_area")
    photos_tab: str = 'new UiSelector().text("Photos")'
    # The grid of the picker (the biggest one on screen); its children are the cells, newest
    # picture first.
    gallery_grid: str = 'new UiSelector().classNameMatches(".*(GridView|RecyclerView)")'
    # Where in a cell its selection circle is, as fractions of the cell's width and height: a
    # tap on the picture itself opens a preview instead of selecting it. The circle then shows
    # the picture's place in the post: "1", "2"...
    select_spot: tuple[float, float] = (0.85, 0.15)
    # "Next (3)" once pictures are selected. A plain "Next" is the camera's, behind the picker.
    picker_next: str = 'new UiSelector().textStartsWith("Next (")'
    # --- the editor (the screen with the photos, before Next) ---
    # The sound at the top: the one TikTok picked by itself until another is chosen. A tap
    # opens the sounds sheet.
    sound_pill: str = _id("tv_top_text")
    editor_next: str = 'new UiSelector().text("Next")'
    # The sounds sheet's tabs; its search is the unlabelled icon to the right of the last one.
    sound_tab: str = 'new UiSelector().text("Recent")'
    icon_button: str = 'new UiSelector().className("android.widget.ImageView").clickable(true)'
    sound_search: str = 'new UiSelector().className("android.widget.EditText")'
    sound_search_go: str = 'new UiSelector().className("android.widget.Button").text("Search")'
    # The results are drawn without any text for UiAutomator: a row per sound in the biggest
    # list, after a row of "Videos with related sounds" (a list of its own). Each row's
    # ✓ ("use this sound") is on its right.
    results_list: str = (
        'new UiSelector().className("androidx.recyclerview.widget.RecyclerView").scrollable(true)'
    )
    nested_list: str = 'new UiSelector().className("androidx.recyclerview.widget.RecyclerView")'
    use_spot: tuple[float, float] = (0.87, 0.5)
    # --- the last screen, with the Post button (which manhwatok never taps) ---
    post_ready: str = 'new UiSelector().className("android.widget.Button").text("Post")'
    title_candidates: tuple[str, ...] = (
        'new UiSelector().className("android.widget.EditText").textStartsWith("Add a catchy title")',
    )
    caption_candidates: tuple[str, ...] = (
        # The box's placeholder, shown as its text while it is empty.
        'new UiSelector().className("android.widget.EditText").textStartsWith("Writing a long description")',
        'new UiSelector().className("android.widget.EditText").textStartsWith("Add description")',
        'new UiSelector().className("android.widget.EditText").instance(1)',
    )
    # "Everyone can view this post" — the row reads who can see it, and a tap opens the choices
    # in a sheet ("Who can view this post") that stays up after one is picked.
    visibility_sheet: str = 'new UiSelector().text("Who can view this post")'
    # What the app calls each Visibility, in its order.
    visibility_names: tuple[str, ...] = ("Everyone", "Friends", "Only you")
    # --- adding the new post to the Story, once the user has posted it ---
    # The profile grid's pinned posts come first and say so; the newest post is the first
    # cell without it. While TikTok is still posting, its cell shows how far it got ("45%").
    pinned_label: str = 'new UiSelector().text("Pinned")'
    # A post's cell shows its view count; banners in the grid ("View expired Stories") don't.
    post_cell_marker: str = _id("tv_play_count")
    videos_tab: str = 'new UiSelector().description("Videos")'
    posting_label: str = 'new UiSelector().textMatches("[0-9]+%")'
    share_button: str = 'new UiSelector().descriptionStartsWith("Share")'
    # The share sheet's second row scrolls sideways; "Add to Story" is past its first screen.
    # "Download" is always on its first screen, so it says where the row is.
    share_row_anchor: str = 'new UiSelector().description("Download")'
    add_to_story: str = 'new UiSelector().description("Add to Story")'
    # The Story screen that opens then: its own "Add to Story" button (a text, not a
    # description, unlike the sheet's) is what shares it.
    story_share: str = 'new UiSelector().text("Add to Story")'
    # The Story screen's tools are unlabelled icons down the right: "Aa" (text) is the fourth,
    # tapped at this fraction of the screen. It opens a text box and a "Done" button.
    story_text_button_spot: tuple[float, float] = (0.922, 0.226)
    story_text_box: str = 'new UiSelector().className("android.widget.EditText")'
    story_text_done: str = 'new UiSelector().text("Done")'
    # The text lands over the middle of the post's card; it is dragged up above the card, to
    # this fraction of the screen.
    story_text_spot: tuple[float, float] = (0.5, 0.17)
    posting_timeout: float = 180.0  # seconds: TikTok finishes posting after the user tapped Post
    launch_timeout: float = 20.0  # seconds: the app opens, a tab or screen shows up
    switch_timeout: float = 15.0  # seconds: the app reloads on another account
    gallery_timeout: float = 20.0  # seconds: the picker lists the pushed slides
    editor_timeout: float = 60.0  # seconds: TikTok takes the photos, shows the editor
    field_timeout: float = 5.0  # seconds: a box or button on a screen already open
    sound_timeout: float = 10.0  # seconds: the sounds sheet opens, a search finds something

    def account_label(self, handle: str) -> str:
        """The "@handle" the Profile tab shows under the account's name."""
        return f"new UiSelector().text({_q('@' + handle)})"

    def account_choice(self, handle: str) -> str:
        """The account's entry in "Switch account": its content-desc is the bare handle."""
        pattern = "(?i)@?" + re.escape(handle)
        return f"new UiSelector().descriptionMatches({_q(pattern)})"

    @property
    def visibility_row(self) -> str:
        """The post screen's row — never the sheet's title, which reads "Who can view…"."""
        names = "|".join(re.escape(n) for n in self.visibility_names)
        return f"new UiSelector().textMatches({_q(f'({names}) can view this post')})"

    def visibility_label(self, visibility: Visibility) -> str:
        return self.visibility_names[list(Visibility).index(visibility)]

    def visibility_choice(self, visibility: Visibility) -> str:
        return f"new UiSelector().text({_q(self.visibility_label(visibility))})"

    def shown_visibility(self, row: str) -> Visibility | None:
        """Which visibility the row names ("Only you can view this post"), or None for a
        wording this doesn't know."""
        text = row.strip()
        for visibility, label in zip(Visibility, self.visibility_names):
            if text.startswith(label + " ") or text == label:
                return visibility
        return None
