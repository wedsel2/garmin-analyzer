from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from garmin_analyzer.db import make_session_factory
from garmin_analyzer.models import GarminLink, LinkStatus, RawPayload, User


@pytest.fixture
def session(db: Engine) -> Iterator[Session]:
    # Closing matters: an open transaction would block the next schema reset.
    with make_session_factory(db)() as session:
        yield session


def make_user(session: Session, email: str = "runner@example.com") -> User:
    user = User(email=email, password_hash="not-a-real-hash")  # noqa: S106
    session.add(user)
    session.commit()
    return user


def test_user_gets_defaults(session: Session) -> None:
    user = make_user(session)

    assert user.id.version == 7
    assert user.is_admin is False
    assert user.created_at.tzinfo is not None


def test_email_is_unique(session: Session) -> None:
    make_user(session)

    with pytest.raises(IntegrityError):
        make_user(session)


def test_garmin_link_round_trip(session: Session) -> None:
    user = make_user(session)
    session.add(GarminLink(user_id=user.id, encrypted_tokens=b"ciphertext"))
    session.commit()
    session.expire_all()

    link = session.get_one(GarminLink, user.id)
    assert link.encrypted_tokens == b"ciphertext"
    assert link.status is LinkStatus.ACTIVE
    assert link.last_synced_at is None
    stored: str = session.execute(text("SELECT status::text FROM garmin_links")).scalar_one()
    assert stored == "active"


def test_raw_payload_round_trip(session: Session) -> None:
    user = make_user(session)
    payload = {"totalSteps": 12345, "nested": {"values": [1, 2.5, None]}}
    session.add(
        RawPayload(
            user_id=user.id,
            endpoint="user_summary",
            resource_key="2026-09-30",
            calendar_date=date(2026, 9, 30),
            payload=payload,
        )
    )
    session.commit()
    session.expire_all()

    stored = session.scalars(select(RawPayload)).one()
    assert stored.payload == payload
    assert stored.calendar_date == date(2026, 9, 30)
    assert stored.fetched_at.tzinfo is not None


def test_raw_payload_is_unique_per_user_endpoint_and_key(session: Session) -> None:
    user = make_user(session)
    other = make_user(session, "cyclist@example.com")
    for owner in (user, other):
        session.add(RawPayload(user_id=owner.id, endpoint="devices", resource_key="-", payload=[]))
    session.commit()

    session.add(RawPayload(user_id=user.id, endpoint="devices", resource_key="-", payload=[]))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_a_user_deletes_their_data(session: Session) -> None:
    user = make_user(session)
    keeper = make_user(session, "cyclist@example.com")
    session.add(GarminLink(user_id=user.id, encrypted_tokens=b"ciphertext"))
    for owner in (user, keeper):
        session.add(RawPayload(user_id=owner.id, endpoint="devices", resource_key="-", payload=[]))
    session.commit()

    session.delete(user)
    session.commit()

    assert session.scalar(select(func.count()).select_from(GarminLink)) == 0
    assert session.scalars(select(RawPayload.user_id)).all() == [keeper.id]
