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


def anthropic_api_key() -> str | None:
    """The key of the instance for the coach; without it a user needs their own."""
    return os.environ.get("ANTHROPIC_API_KEY", "").strip() or None


def coach_model() -> str:
    return os.environ.get("COACH_MODEL", "").strip() or "claude-opus-5-5"


def coach_reports_per_day() -> int:
    """How many reports a user may have written per day on the key of the instance."""
    text = os.environ.get("COACH_REPORTS_PER_DAY", "").strip() or "3"
    try:
        limit = int(text)
    except ValueError:
        raise ConfigError("COACH_REPORTS_PER_DAY is not a whole number") from None
    if limit < 1:
        raise ConfigError("COACH_REPORTS_PER_DAY must be 1 or more")
    return limit
