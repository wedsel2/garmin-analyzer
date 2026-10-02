"""Encryption of Garmin tokens at rest.

Tokens give lasting access to a Garmin account, so the database only ever holds
them encrypted. The key comes from TOKEN_ENCRYPTION_KEY and is not stored in
the database, which means a database dump alone does not expose the tokens.
"""

from cryptography.fernet import Fernet, InvalidToken

from garmin_analyzer.config import ConfigError


class TokenDecryptError(Exception):
    """Stored tokens could not be decrypted, most likely because the key changed."""


def generate_key() -> str:
    return Fernet.generate_key().decode()


class TokenCipher:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key)
        except ValueError as error:
            raise ConfigError(
                "TOKEN_ENCRYPTION_KEY is not a valid key; "
                "create one with: garmin-analyzer generate-key"
            ) from error

    def encrypt(self, tokens: str) -> bytes:
        return self._fernet.encrypt(tokens.encode())

    def decrypt(self, encrypted: bytes) -> str:
        try:
            return self._fernet.decrypt(encrypted).decode()
        except InvalidToken as error:
            raise TokenDecryptError("stored Garmin tokens cannot be decrypted") from error
