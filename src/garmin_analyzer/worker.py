"""The scheduled worker: syncs every linked user at an interval.

One process that looks once a minute for users whose last sync is older than
the interval. Nothing is queued: what is due is read from the database each
time, so a restart loses nothing. See ADR 17.
"""

import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from garmin_analyzer.db import make_session_factory
from garmin_analyzer.models import GarminLink, LinkStatus, User

TICK_SECONDS = 60.0

# Syncs one user and reports on it. Must not raise for a sync that failed.
SyncOne = Callable[[Session, User], object]


def due_users(
    session: Session, now: datetime, interval: timedelta, attempted: dict[uuid.UUID, datetime]
) -> list[User]:
    """Users with an active link whose last sync, and last attempt, are older than the interval.

    A sync that failed or stopped early leaves the time of the last sync as it
    was. The attempts, kept in memory, stop such a user from being tried again
    every minute.
    """
    before = now - interval
    users = session.scalars(
        select(User)
        .join(GarminLink, GarminLink.user_id == User.id)
        .where(
            GarminLink.status == LinkStatus.ACTIVE,
            or_(GarminLink.last_synced_at.is_(None), GarminLink.last_synced_at <= before),
        )
        # Whoever has never been synced, such as a user who just linked, goes first.
        .order_by(GarminLink.last_synced_at.asc().nulls_first(), User.email)
    )
    return [user for user in users if user.id not in attempted or attempted[user.id] <= before]


def run_due(
    engine: Engine,
    sync_one: SyncOne,
    interval: timedelta,
    attempted: dict[uuid.UUID, datetime],
    now: datetime | None = None,
) -> int:
    """Sync the users that are due, one after the other. Returns how many."""
    with make_session_factory(engine)() as session:
        users = due_users(session, now or datetime.now(UTC), interval, attempted)
        for user in users:
            try:
                sync_one(session, user)
            finally:
                attempted[user.id] = now or datetime.now(UTC)
    return len(users)


def run_forever(
    engine: Engine,
    sync_one: SyncOne,
    interval: timedelta,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    attempted: dict[uuid.UUID, datetime] = {}
    while True:
        try:
            run_due(engine, sync_one, interval, attempted)
        except SQLAlchemyError as error:
            # The database may be restarting; the next round tries again.
            print(f"database error, trying again in a minute: {error}", file=sys.stderr)
        sleep(TICK_SECONDS)
