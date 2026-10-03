from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from garmin_analyzer.db import make_session_factory
from garmin_analyzer.models import PasswordLink, User
from garmin_analyzer.password_links import LIFETIME, create_link, link_user, use_link
from garmin_analyzer.passwords import PasswordError, verify_password
from garmin_analyzer.sessions import create_session, session_user
from garmin_analyzer.users import NO_PASSWORD, add_user

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"  # noqa: S105


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
    return session.scalar(select(func.count()).select_from(PasswordLink)) or 0


def test_a_link_leads_to_its_user_and_its_token_is_not_stored(session: Session, user: User) -> None:
    token = create_link(session, user.id, NOW)
    session.commit()

    found = link_user(session, token, NOW)

    assert found is not None
    assert found.id == user.id
    assert session.scalar(select(PasswordLink.token_hash)) != token
    assert link_user(session, token + "x", NOW) is None


def test_a_link_runs_out(session: Session, user: User) -> None:
    token = create_link(session, user.id, NOW)
    session.commit()

    assert link_user(session, token, NOW + LIFETIME - timedelta(seconds=1)) is not None
    assert link_user(session, token, NOW + LIFETIME) is None
    assert use_link(session, token, PASSWORD, NOW + LIFETIME) is None
    assert user.password_hash == NO_PASSWORD


def test_a_new_link_replaces_the_old_one(session: Session, user: User) -> None:
    old = create_link(session, user.id, NOW)
    new = create_link(session, user.id, NOW)
    session.commit()

    assert count(session) == 1
    assert link_user(session, old, NOW) is None
    assert link_user(session, new, NOW) is not None


def test_using_a_link_sets_the_password_once_and_signs_out_elsewhere(
    session: Session, user: User
) -> None:
    signed_in = create_session(session, user.id, NOW)
    token = create_link(session, user.id, NOW)
    session.commit()

    used_by = use_link(session, token, PASSWORD, NOW)
    session.commit()

    assert used_by is not None
    assert used_by.id == user.id
    assert verify_password(user.password_hash, PASSWORD)
    assert session_user(session, signed_in, NOW) is None
    assert use_link(session, token, "another long password", NOW) is None
    assert verify_password(user.password_hash, PASSWORD)


def test_a_refused_password_leaves_the_link_usable(session: Session, user: User) -> None:
    token = create_link(session, user.id, NOW)
    session.commit()

    with pytest.raises(PasswordError):
        use_link(session, token, "short", NOW)
    session.rollback()

    assert link_user(session, token, NOW) is not None


def test_links_go_with_their_user(session: Session, user: User) -> None:
    create_link(session, user.id, NOW)
    session.commit()

    session.delete(user)
    session.commit()

    assert count(session) == 0
