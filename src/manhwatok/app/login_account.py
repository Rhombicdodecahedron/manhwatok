"""Log an account in to TikTok once, by hand, in its own browser profile (manhwatok never sees
the password); find or delete that saved login."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from manhwatok.app.post_tools import ProgressFn
from manhwatok.domain.account import Account, normalize_handle
from manhwatok.domain.errors import InvalidName, StorageError
from manhwatok.ports.store import AccountRepository
from manhwatok.ports.uploader import Uploader


def quit_shortcut() -> str:
    """The keys that quit Chrome on this platform; closing its last window isn't enough on a
    Mac, where Chrome keeps running."""
    return "⌘Q" if sys.platform == "darwin" else "Ctrl+Q"


def login_account(
    handle: str, accounts: AccountRepository, uploader: Uploader, progress: ProgressFn
) -> Account:
    """Returns once the user has quit the browser."""
    account = accounts.get(normalize_handle(handle))
    progress(
        f"Log in to {account.display} in the Chrome window, "
        f"then quit that Chrome ({quit_shortcut()})."
    )
    try:
        uploader.login(account.handle)
    finally:
        uploader.close()
    return account


def _validate_profile_path(browser_dir: Path, name: str) -> Path:
    """Build and validate the profile path stays within browser_dir. A link is never followed
    (nor deleted): manhwatok only ever creates real folders there."""
    if name in (".", ".."):
        raise InvalidName(f"invalid profile folder name: {name!r}")
    path = browser_dir / name
    if path.is_symlink():
        raise StorageError(
            f"the saved TikTok login for @{name} is a link — delete it yourself: {path}"
        )
    if path.resolve().parent != browser_dir.resolve():
        raise InvalidName("profile path would escape the browser directory")
    return path


def saved_login(browser_dir: Path, handle: str) -> Path | None:
    """The account's browser profile folder, if `manhwatok login` ever created one."""
    name = normalize_handle(handle)
    folder = _validate_profile_path(browser_dir, name)
    return folder if folder.is_dir() else None


def forget_login(browser_dir: Path, handle: str) -> None:
    """Delete the account's saved browser profile, if it exists."""
    name = normalize_handle(handle)
    folder = _validate_profile_path(browser_dir, name)
    if not folder.exists():
        return
    try:
        shutil.rmtree(folder)
    except OSError as e:
        raise StorageError(f"could not delete the saved login {folder}: {e}") from e
