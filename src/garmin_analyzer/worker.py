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
# A sync asked for on the account page does not wait for the interval, but it
# does wait this long after the last sync or attempt, so pressing the button
# again and again does not become a stream of requests to Garmin.
REQUEST_GAP = timedelta(minutes=5)

# Syncs one user and reports on it. Must not raise for a sync that failed.
# The number is how many days the user asked to have fetched again, if they asked.
SyncOne = Callable[[Session, User, int | None], object]


def due_users(
    session: Session, now: datetime, interval: timedelta, attempted: dict[uuid.UUID, datetime]
) -> list[User]:
    """Users with an active link whose last sync, and last attempt, are older than the interval.

    A sync that failed or stopped early leaves the time of the last sync as it
    was. The attempts, kept in memory, stop such a user from being tried again
    every minute.

    For a user who asked for a sync, REQUEST_GAP takes the place of the interval.
    """
    before = now - interval
    rows = session.execute(
        select(User, GarminLink.sync_requested_at, GarminLink.last_synced_at)
        .join(GarminLink, GarminLink.user_id == User.id)
        .where(
            GarminLink.status == LinkStatus.ACTIVE,
            or_(
                GarminLink.last_synced_at.is_(None),
                GarminLink.last_synced_at <= before,
                GarminLink.sync_requested_at.is_not(None),
            ),
        )
        # Whoever has never been synced, such as a user who just linked, goes first.
        .order_by(GarminLink.last_synced_at.asc().nulls_first(), User.email)
    )
    users = []
    for user, requested, synced in rows:
        limit = before
        if requested is not None:
            limit = max(before, now - REQUEST_GAP)
            if synced is not None and synced > limit:
                continue
        if user.id not in attempted or attempted[user.id] <= limit:
            users.append(user)
    return users


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
            # A request is spent when its sync starts, however that sync ends:
            # one press of the button is one sync.
            link = session.get_one(GarminLink, user.id)
            days = link.sync_requested_days if link.sync_requested_at else None
            link.sync_requested_at = link.sync_requested_days = None
            session.commit()
            try:
                sync_one(session, user, days)
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
