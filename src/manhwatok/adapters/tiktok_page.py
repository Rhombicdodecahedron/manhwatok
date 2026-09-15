"""Everything manhwatok knows about TikTok's website: URLs, selectors and timeouts. This is the
only file with TikTok specifics — when TikTok changes its pages, run
`manhwatok upload <id> --debug` and update these from the saved page.html."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TikTokPage:
    login_url: str = "https://www.tiktok.com/login"
    upload_url: str = "https://www.tiktok.com/tiktokstudio/upload"
    # A logged-out browser gets sent from the upload page to a URL containing this.
    login_url_marker: str = "/login"
    # The upload page's file input (usually hidden); it must take several files at once.
    file_input: str = "input[type=file]"
    # Where the caption goes, most specific first.
    caption_candidates: tuple[str, ...] = (
        '[class*="caption"] [contenteditable="true"]',
        '[contenteditable="true"]',
        "textarea",
    )
    # Appears once TikTok has taken the files and shows the post editor (never clicked).
    editor_ready: str = '[contenteditable="true"], button[data-e2e="post_video_button"]'
    page_timeout: float = 30.0  # seconds: load the page, find the file input
    editor_timeout: float = 60.0  # seconds: TikTok processes the files, shows the editor
    caption_timeout: float = 5.0  # seconds: the caption box, once the editor is there
