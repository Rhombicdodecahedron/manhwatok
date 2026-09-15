import pytest

from manhwatok.domain.errors import (
    AccountNotFound,
    AlreadyExists,
    InvalidName,
    ManhwatokError,
    ThemeNotFound,
)


@pytest.mark.parametrize("error", [AccountNotFound, ThemeNotFound, InvalidName, AlreadyExists])
def test_new_errors_are_user_facing(error):
    assert issubclass(error, ManhwatokError)
