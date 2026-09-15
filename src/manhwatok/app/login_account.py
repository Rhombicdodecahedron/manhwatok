"""Log an account in to TikTok once, by hand, in its own browser profile (manhwatok never sees
the password); find or delete that saved login."""

from __future__ import annotations

import shutil
from pathlib import Path

from manhwatok.app.post_tools import ProgressFn
from manhwatok.domain.account import Account, normalize_handle
from manhwatok.domain.errors import StorageError
from manhwatok.ports.store import AccountRepository
from manhwatok.ports.uploader import Uploader


def login_account(
    handle: str, accounts: AccountRepository, uploader: Uploader, progress: ProgressFn
) -> Account:
    """Returns once the user has closed the browser window."""
    account = accounts.get(normalize_handle(handle))
    progress(f"Log in to {account.display} in the browser, then close the window.")
    try:
        uploader.login(account.handle)
    finally:
        uploader.close()
    return account


def saved_login(browser_dir: Path, handle: str) -> Path | None:
    """The account's browser profile folder, if `manhwatok login` ever created one."""
    folder = browser_dir / normalize_handle(handle)
    return folder if folder.is_dir() else None


def forget_login(folder: Path) -> None:
    try:
        shutil.rmtree(folder)
    except OSError as e:
        raise StorageError(f"could not delete the saved login {folder}: {e}") from e
