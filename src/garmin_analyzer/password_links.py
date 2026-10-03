"""Links with which a user sets their password: invites and resets.

The administrator passes the link on; no email is sent (ADR 8). The link holds
a random token, of which only the SHA-256 hash is stored. It works once, for a
week, and a new link for the same user replaces the old one.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from garmin_analyzer.models import PasswordLink, User
from garmin_analyzer.users import set_password

LIFETIME = timedelta(days=7)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_link(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> str:
    """Make the one link of a user and return the token for its address."""
    now = now or datetime.now(UTC)
    db.execute(delete(PasswordLink).where(PasswordLink.user_id == user_id))
    token = secrets.token_urlsafe(32)
    db.add(PasswordLink(user_id=user_id, token_hash=_hash(token), expires_at=now + LIFETIME))
    return token


def link_user(
    db: Session, token: str, now: datetime | None = None, for_update: bool = False
) -> User | None:
    """The user a link is for, or None when it is unknown, used or expired."""
    now = now or datetime.now(UTC)
    query = select(PasswordLink).where(PasswordLink.token_hash == _hash(token))
    if for_update:
        # Two uses at the same moment take turns, and the second finds it gone.
        query = query.with_for_update()
    link = db.scalar(query)
    if link is None or link.expires_at <= now:
        return None
    return db.get(User, link.user_id)


def use_link(db: Session, token: str, password: str, now: datetime | None = None) -> User | None:
    """Set the password of the user a link is for, and spend the link.

    Returns None when the link is not valid. Raises PasswordError when the
    password is refused; the link can then be used again.
    """
    user = link_user(db, token, now, for_update=True)
    if user is None:
        return None
    # Also removes the link.
    set_password(db, user, password)
    return user
