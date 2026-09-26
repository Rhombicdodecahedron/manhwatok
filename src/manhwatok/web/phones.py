"""The phones for the web pages: the list, and each phone's screen — grabbed only when a page
asks, one grab per phone at a time, and reused for a moment so several tabs share it."""

from __future__ import annotations

import threading
import time
from typing import Callable

from manhwatok.adapters.phones import Phone, has_app, list_phones, screencap


class Phones:
    def __init__(
        self,
        list_fn: Callable[[], list[Phone]] = list_phones,
        screen_fn: Callable[[str], bytes] = screencap,
        app_fn: Callable[[str, str], bool] = has_app,
        cache_s: float = 0.8,
    ) -> None:
        self._list, self._screen, self._app, self._cache_s = list_fn, screen_fn, app_fn, cache_s
        self._lock = threading.Lock()
        self._grabbing: dict[str, threading.Lock] = {}
        self._frames: dict[str, tuple[float, bytes]] = {}

    def list(self) -> list[Phone]:
        return self._list()

    def tiktok(self, serial: str, package: str) -> bool:
        try:
            return self._app(serial, package)
        except Exception:
            return False

    def screen(self, serial: str) -> bytes:
        with self._lock:
            grabbing = self._grabbing.setdefault(serial, threading.Lock())
        with grabbing:
            at, frame = self._frames.get(serial, (0.0, b""))
            if frame and time.monotonic() - at < self._cache_s:
                return frame
            frame = self._screen(serial)
            self._frames[serial] = (time.monotonic(), frame)
            return frame
