"""Settings read from the environment."""

import os


class ConfigError(Exception):
    """A required setting is missing or invalid."""


def database_url() -> str:
    """Return DATABASE_URL in the form SQLAlchemy needs for the psycopg driver."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ConfigError("DATABASE_URL is not set")
    for scheme in ("postgresql://", "postgres://"):
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url.removeprefix(scheme)
    return url


def token_encryption_key() -> str:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise ConfigError(
            "TOKEN_ENCRYPTION_KEY is not set; create one with: garmin-analyzer generate-key"
        )
    return key
