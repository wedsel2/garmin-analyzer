"""Password hashing with argon2."""

from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 12
# Long enough for any passphrase; stops a huge input from keeping the hasher busy.
MAX_LENGTH = 256

_hasher = PasswordHasher()


class PasswordError(Exception):
    """The password does not meet the rules."""


def hash_password(password: str) -> str:
    if len(password) < MIN_LENGTH:
        raise PasswordError(f"use a password of at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise PasswordError(f"use a password of at most {MAX_LENGTH} characters")
    return _hasher.hash(password)


@cache
def _dummy_hash() -> str:
    return _hasher.hash("no account has this password")


def verify_password(password_hash: str | None, password: str) -> bool:
    """True when the password matches the hash.

    Pass None for an account that does not exist. That, and an account without
    a password yet (users.NO_PASSWORD), still costs one hash check, so a failed
    sign-in takes as long whether or not the address is known.
    """
    if len(password) > MAX_LENGTH:
        return False
    usable = password_hash is not None and password_hash.startswith("$argon2")
    try:
        _hasher.verify(password_hash if usable and password_hash else _dummy_hash(), password)
    except VerificationError, InvalidHashError:
        return False
    return usable


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with older settings than the current ones."""
    return _hasher.check_needs_rehash(password_hash)
