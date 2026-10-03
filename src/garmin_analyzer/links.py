"""Storing and using the Garmin link of a user."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from garmin_analyzer.garmin import GarminSession, RelinkRequired
from garmin_analyzer.models import GarminLink, LinkStatus
from garmin_analyzer.tokens import TokenCipher


class NotLinked(Exception):
    """The user has no Garmin link."""


class AlreadySyncing(Exception):
    """Another sync of the same user is running."""


@contextmanager
def sync_lock(session: Session, user_id: uuid.UUID) -> Iterator[None]:
    """Allow one sync per user at a time. Raises AlreadySyncing when one is running.

    Two syncs would each refresh the tokens and the last to finish would store
    its own, which Garmin may no longer accept. The lock is held on a
    connection of its own, as the session commits many times during a sync,
    and PostgreSQL drops it when the process dies.
    """
    key = func.hashtextextended(f"garmin-sync:{user_id}", 0)
    with session.get_bind().engine.connect() as connection:
        locked = connection.scalar(select(func.pg_try_advisory_lock(key)))
        connection.commit()
        if not locked:
            raise AlreadySyncing(f"another sync of user {user_id} is running")
        try:
            yield
        finally:
            connection.execute(select(func.pg_advisory_unlock(key)))
            connection.commit()


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
    When Garmin accepts them, a link that was marked is active again.
    """
    link = session.get(GarminLink, user_id)
    if link is None:
        raise NotLinked(f"user {user_id} has no Garmin link")
    try:
        garmin = GarminSession.from_tokens(cipher.decrypt(link.encrypted_tokens))
    except RelinkRequired as error:
        mark_needs_relink(session, user_id, str(error))
        raise
    link.status = LinkStatus.ACTIVE
    link.last_error = None
    save_tokens(session, user_id, cipher, garmin)
    return garmin


def save_tokens(
    session: Session, user_id: uuid.UUID, cipher: TokenCipher, garmin: GarminSession
) -> None:
    """Persist the tokens of a session, when a refresh has replaced them."""
    link = session.get_one(GarminLink, user_id)
    tokens = garmin.tokens()
    if cipher.decrypt(link.encrypted_tokens) != tokens:
        link.encrypted_tokens = cipher.encrypt(tokens)


def mark_needs_relink(session: Session, user_id: uuid.UUID, reason: str) -> None:
    link = session.get_one(GarminLink, user_id)
    link.status = LinkStatus.NEEDS_RELINK
    link.last_error = reason
