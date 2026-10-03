"""Server-side sessions of signed-in users.

The browser holds a random token in a cookie. The database holds only its
SHA-256 hash, so a database dump cannot be used to sign in.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from garmin_analyzer.models import User, WebSession

# A session ends after this long without a request.
IDLE_LIFETIME = timedelta(days=30)
# How often a session in use has its expiry moved forward.
RENEW_AFTER = timedelta(hours=1)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> str:
    """Start a session and return the token for the cookie."""
    now = now or datetime.now(UTC)
    db.execute(delete(WebSession).where(WebSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    db.add(
        WebSession(
            token_hash=_hash(token),
            user_id=user_id,
            last_seen_at=now,
            expires_at=now + IDLE_LIFETIME,
        )
    )
    return token


def session_user(db: Session, token: str, now: datetime | None = None) -> User | None:
    """The user a token belongs to, or None when it is unknown or expired."""
    now = now or datetime.now(UTC)
    web_session = db.get(WebSession, _hash(token))
    if web_session is None or web_session.expires_at <= now:
        return None
    if now - web_session.last_seen_at >= RENEW_AFTER:
        web_session.last_seen_at = now
        web_session.expires_at = now + IDLE_LIFETIME
        db.commit()
    return db.get(User, web_session.user_id)


def end_session(db: Session, token: str) -> None:
    db.execute(delete(WebSession).where(WebSession.token_hash == _hash(token)))


def end_sessions_of(db: Session, user_id: uuid.UUID) -> None:
    """Sign a user out everywhere, as after a password change."""
    db.execute(delete(WebSession).where(WebSession.user_id == user_id))
