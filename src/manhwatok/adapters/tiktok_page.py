"""Everything manhwatok knows about TikTok's website: URLs, selectors and timeouts. This is the
only file with TikTok specifics — when TikTok changes its pages, run
`manhwatok upload <id> --debug` and update these from the saved page.html."""

from __future__ import annotations

import json
from dataclasses import dataclass


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
    page_timeout: float = 30.0  # seconds: load the page, find the file input
    editor_timeout: float = 60.0  # seconds: TikTok processes the files, shows the editor
    caption_timeout: float = 5.0  # seconds: the title/description boxes, once the editor is there
    hashtag_timeout: float = 3.0  # seconds: TikTok suggests a typed hashtag
    sound_timeout: float = 10.0  # seconds: the Sounds dialog opens, a search finds something

    def hashtag_choice(self, tag: str) -> str:
        """The suggestion that is exactly `tag` (TikTok lists hashtags in lowercase)."""
        return f"{self.hashtag_option}:has({self.hashtag_topic}:text-is({json.dumps(tag.lower())}))"
