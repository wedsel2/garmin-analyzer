"""Encryption of Garmin tokens at rest.

Tokens give lasting access to a Garmin account, so the database only ever holds
them encrypted. The key comes from TOKEN_ENCRYPTION_KEY and is not stored in
the database, which means a database dump alone does not expose the tokens.

To replace the key, TOKEN_ENCRYPTION_KEY can hold several keys separated by
commas: the first one encrypts, all of them decrypt. See ADR 14.
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from garmin_analyzer.config import ConfigError


class TokenDecryptError(Exception):
    """Stored tokens could not be decrypted, most likely because the key changed."""


def generate_key() -> str:
    return Fernet.generate_key().decode()


class TokenCipher:
    def __init__(self, keys: str) -> None:
        try:
            ciphers = [Fernet(key) for key in keys.replace(",", " ").split()]
        except ValueError as error:
            raise ConfigError(
                "TOKEN_ENCRYPTION_KEY is not a valid key; "
                "create one with: garmin-analyzer generate-key"
            ) from error
        if not ciphers:
            raise ConfigError("TOKEN_ENCRYPTION_KEY holds no key")
        self._current = ciphers[0]
        self._all = MultiFernet(ciphers)

    def encrypt(self, tokens: str) -> bytes:
        return self._current.encrypt(tokens.encode())

    def decrypt(self, encrypted: bytes) -> str:
        try:
            return self._all.decrypt(encrypted).decode()
        except InvalidToken as error:
            raise TokenDecryptError("stored Garmin tokens cannot be decrypted") from error

    def is_current(self, encrypted: bytes) -> bool:
        """Whether the tokens were encrypted with the first key, the one to keep."""
        try:
            self._current.decrypt(encrypted)
        except InvalidToken:
            return False
        return True
