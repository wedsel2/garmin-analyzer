import pytest

from garmin_analyzer.passwords import (
    MAX_LENGTH,
    PasswordError,
    hash_password,
    needs_rehash,
    verify_password,
)
from garmin_analyzer.users import NO_PASSWORD

PASSWORD = "correct horse battery"  # noqa: S105


def test_a_hash_verifies_only_its_own_password() -> None:
    hashed = hash_password(PASSWORD)

    assert hashed.startswith("$argon2id$")
    assert PASSWORD not in hashed
    assert verify_password(hashed, PASSWORD)
    assert not verify_password(hashed, PASSWORD + "!")
    assert not needs_rehash(hashed)


@pytest.mark.parametrize("password", ["short", "x" * (MAX_LENGTH + 1)])
def test_too_short_and_too_long_passwords_are_refused(password: str) -> None:
    with pytest.raises(PasswordError):
        hash_password(password)


@pytest.mark.parametrize("stored", [None, NO_PASSWORD, "not-a-hash", "$argon2id$broken"])
def test_nothing_matches_a_missing_or_unusable_hash(stored: str | None) -> None:
    assert not verify_password(stored, PASSWORD)
    assert not verify_password(stored, "no account has this password")


def test_an_overlong_password_never_matches() -> None:
    assert not verify_password(hash_password(PASSWORD), "x" * (MAX_LENGTH + 1))
