"""The Android phones plugged in over USB, as adb sees them, and a picture of a phone's screen.
Everything goes through `adb`; nothing here drives the phone."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable

from manhwatok.adapters.appium_uploader import ADB_HINT, _find_adb
from manhwatok.domain.errors import ManhwatokError, UploadUnavailable

SERIAL = re.compile(r"^[A-Za-z0-9._:-]+$")
PNG = b"\x89PNG\r\n\x1a\n"

Run = Callable[[list[str]], str]
RunBytes = Callable[[list[str]], bytes]


@dataclass(frozen=True)
class Phone:
    serial: str
    state: str
    model: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "device"

    @property
    def problem(self) -> str:
        if self.ready:
            return ""
        if self.state == "unauthorized":
            return "needs you to allow USB debugging on the phone"
        if self.state == "offline":
            return "is offline — unplug it and plug it back in"
        return f"is {self.state}"


def check_serial(serial: str) -> str:
    if not SERIAL.match(serial or ""):
        raise ManhwatokError(f"not a phone serial: {serial!r}")
    return serial


def _adb() -> str:
    adb = _find_adb()
    if adb is None:
        raise UploadUnavailable(ADB_HINT)
    return adb


def _run(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ManhwatokError(f"adb failed: {e}") from e


def _run_bytes(argv: list[str]) -> bytes:
    try:
        return subprocess.run(argv, capture_output=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ManhwatokError(f"adb failed: {e}") from e


def list_phones(run: Run | None = None) -> list[Phone]:
    """Every phone adb knows of, ready or not."""
    out = (run or _run)([_adb() if run is None else "adb", "devices", "-l"])
    found = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        model = next((p[6:] for p in parts[2:] if p.startswith("model:")), "")
        found.append(Phone(parts[0], parts[1], model.replace("_", " ")))
    return found


def has_app(serial: str, package: str, run: Run | None = None) -> bool:
    argv = [_adb() if run is None else "adb", "-s", check_serial(serial),
            "shell", "pm", "list", "packages", package]
    return f"package:{package}" in (run or _run)(argv).split()


def screencap(serial: str, run_bytes: RunBytes | None = None) -> bytes:
    argv = [_adb() if run_bytes is None else "adb", "-s", check_serial(serial),
            "exec-out", "screencap", "-p"]
    data = (run_bytes or _run_bytes)(argv)
    start = data.find(PNG)  # a phone with two screens warns before the picture
    if start > 0:
        data = data[start:]
    if not data.startswith(PNG):
        said = data[:120].decode("utf-8", "replace").strip() or "no picture"
        raise ManhwatokError(f"could not see the screen of {serial}: {said}")
    return data
