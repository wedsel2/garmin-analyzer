"""Storing and using the Garmin link of a user."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from garmin_analyzer.garmin import GarminSession, RelinkRequired
from garmin_analyzer.models import GarminLink, LinkStatus
from garmin_analyzer.tokens import TokenCipher


class NotLinked(Exception):
    """The user has no Garmin link."""


def store_link(
    session: Session, user_id: uuid.UUID, cipher: TokenCipher, garmin: GarminSession
) -> GarminLink:
    """Create or replace the link of a user with freshly obtained tokens."""
    link = session.get(GarminLink, user_id)
    if link is None:
        link = GarminLink(user_id=user_id, encrypted_tokens=b"")
        session.add(link)
    link.encrypted_tokens = cipher.encrypt(garmin.tokens())
    link.status = LinkStatus.ACTIVE
    link.linked_at = datetime.now(UTC)
    link.last_error = None
    return link


def open_link(session: Session, user_id: uuid.UUID, cipher: TokenCipher) -> GarminSession:
    """Open a Garmin session from the stored tokens of a user.

    When Garmin rejects the tokens, the link is marked as needing a new sign-in
    and RelinkRequired is raised. Nothing retries against the sign-in site.
    """
    link = session.get(GarminLink, user_id)
    if link is None:
        raise NotLinked(f"user {user_id} has no Garmin link")
    try:
        garmin = GarminSession.from_tokens(cipher.decrypt(link.encrypted_tokens))
    except RelinkRequired as error:
        mark_needs_relink(session, user_id, str(error))
        raise
    save_tokens(session, user_id, cipher, garmin)
    return garmin


def save_tokens(
    session: Session, user_id: uuid.UUID, cipher: TokenCipher, garmin: GarminSession
) -> None:
    """Persist the tokens of a session, which a refresh may have replaced."""
    link = session.get_one(GarminLink, user_id)
    link.encrypted_tokens = cipher.encrypt(garmin.tokens())


def mark_needs_relink(session: Session, user_id: uuid.UUID, reason: str) -> None:
    link = session.get_one(GarminLink, user_id)
    link.status = LinkStatus.NEEDS_RELINK
    link.last_error = reason
