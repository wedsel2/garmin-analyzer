from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from garmin_analyzer.db import make_session_factory
from garmin_analyzer.models import User, WebSession
from garmin_analyzer.sessions import (
    IDLE_LIFETIME,
    create_session,
    end_session,
    end_sessions_of,
    session_user,
)
from garmin_analyzer.users import add_user

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


@pytest.fixture
def session(db: Engine) -> Iterator[Session]:
    with make_session_factory(db)() as session:
        yield session


@pytest.fixture
def user(session: Session) -> User:
    user = add_user(session, "runner@example.com")
    session.commit()
    return user


def count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(WebSession)) or 0


def test_a_token_leads_to_its_user_and_is_not_stored(session: Session, user: User) -> None:
    token = create_session(session, user.id, NOW)
    session.commit()

    found = session_user(session, token, NOW)

    assert found is not None
    assert found.id == user.id
    assert session.scalar(select(WebSession.token_hash)) != token
    assert session_user(session, token + "x", NOW) is None


def test_a_session_ends_after_the_idle_lifetime(session: Session, user: User) -> None:
    token = create_session(session, user.id, NOW)
    session.commit()

    assert session_user(session, token, NOW + IDLE_LIFETIME - timedelta(seconds=1)) is not None
    # The request just before the end moved the end forward.
    assert session_user(session, token, NOW + IDLE_LIFETIME + timedelta(days=1)) is not None
    assert session_user(session, token, NOW + 3 * IDLE_LIFETIME) is None


def test_signing_in_removes_expired_sessions(session: Session, user: User) -> None:
    create_session(session, user.id, NOW)
    create_session(session, user.id, NOW + IDLE_LIFETIME)
    session.commit()

    assert count(session) == 1


def test_ending_sessions(session: Session, user: User) -> None:
    other = add_user(session, "cyclist@example.com")
    session.flush()
    first = create_session(session, user.id, NOW)
    second = create_session(session, user.id, NOW)
    kept = create_session(session, other.id, NOW)
    session.commit()

    end_session(session, first)
    assert session_user(session, first, NOW) is None
    assert session_user(session, second, NOW) is not None

    end_sessions_of(session, user.id)
    session.commit()
    assert session_user(session, second, NOW) is None
    assert session_user(session, kept, NOW) is not None


def test_sessions_go_with_their_user(session: Session, user: User) -> None:
    create_session(session, user.id, NOW)
    session.commit()

    session.delete(user)
    session.commit()

    assert count(session) == 0
