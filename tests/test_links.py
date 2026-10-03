import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from garmin_analyzer import links
from garmin_analyzer.db import make_session_factory
from garmin_analyzer.garmin import GarminSession, RelinkRequired
from garmin_analyzer.links import AlreadySyncing, NotLinked, open_link, store_link
from garmin_analyzer.models import GarminLink, LinkStatus, User
from garmin_analyzer.tokens import TokenCipher, generate_key


class StubGarmin(GarminSession):
    """A Garmin session that holds tokens without a library behind it."""

    def __init__(self, tokens: str) -> None:
        self._tokens = tokens

    def tokens(self) -> str:
        return self._tokens


@pytest.fixture
def session(db: Engine) -> Iterator[Session]:
    with make_session_factory(db)() as session:
        yield session


@pytest.fixture
def user(session: Session) -> User:
    user = User(email="runner@example.com", password_hash="not-a-real-hash")  # noqa: S106
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def cipher() -> TokenCipher:
    return TokenCipher(generate_key())


def test_link_is_stored_encrypted(session: Session, user: User, cipher: TokenCipher) -> None:
    store_link(session, user.id, cipher, StubGarmin("first-tokens"))
    session.commit()
    session.expire_all()

    link = session.get_one(GarminLink, user.id)
    assert b"first-tokens" not in link.encrypted_tokens
    assert cipher.decrypt(link.encrypted_tokens) == "first-tokens"
    assert link.status is LinkStatus.ACTIVE


def test_linking_again_replaces_tokens_and_clears_the_error(
    session: Session, user: User, cipher: TokenCipher
) -> None:
    store_link(session, user.id, cipher, StubGarmin("first-tokens"))
    links.mark_needs_relink(session, user.id, "rejected")
    session.commit()

    store_link(session, user.id, cipher, StubGarmin("second-tokens"))
    session.commit()
    session.expire_all()

    link = session.get_one(GarminLink, user.id)
    assert cipher.decrypt(link.encrypted_tokens) == "second-tokens"
    assert (link.status, link.last_error) == (LinkStatus.ACTIVE, None)


def test_opening_a_link_saves_refreshed_tokens(
    session: Session, user: User, cipher: TokenCipher, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_link(session, user.id, cipher, StubGarmin("stored-tokens"))
    session.commit()
    seen: list[str] = []

    def refreshed(tokens: str) -> GarminSession:
        seen.append(tokens)
        # The library refreshed while logging in and now holds new tokens.
        return StubGarmin("refreshed-tokens")

    monkeypatch.setattr(GarminSession, "from_tokens", refreshed)

    garmin = open_link(session, user.id, cipher)
    session.commit()
    session.expire_all()

    assert seen == ["stored-tokens"]
    assert garmin.tokens() == "refreshed-tokens"
    stored = session.get_one(GarminLink, user.id).encrypted_tokens
    assert cipher.decrypt(stored) == "refreshed-tokens"


def test_rejected_tokens_mark_the_link_for_relinking(
    session: Session, user: User, cipher: TokenCipher, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_link(session, user.id, cipher, StubGarmin("stored-tokens"))
    session.commit()

    def rejected(tokens: str) -> GarminSession:
        raise RelinkRequired("Garmin rejected the tokens")

    monkeypatch.setattr(GarminSession, "from_tokens", rejected)

    with pytest.raises(RelinkRequired):
        open_link(session, user.id, cipher)
    session.commit()
    session.expire_all()

    link = session.get_one(GarminLink, user.id)
    assert link.status is LinkStatus.NEEDS_RELINK
    assert link.last_error == "Garmin rejected the tokens"
    # The old tokens are kept; only a successful new link replaces them.
    assert cipher.decrypt(link.encrypted_tokens) == "stored-tokens"


def test_accepted_tokens_make_a_marked_link_active_again(
    session: Session, user: User, cipher: TokenCipher, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_link(session, user.id, cipher, StubGarmin("stored-tokens"))
    links.mark_needs_relink(session, user.id, "marked during an outage")
    session.commit()
    monkeypatch.setattr(GarminSession, "from_tokens", StubGarmin)

    open_link(session, user.id, cipher)
    session.commit()
    session.expire_all()

    link = session.get_one(GarminLink, user.id)
    assert (link.status, link.last_error) == (LinkStatus.ACTIVE, None)


def test_unchanged_tokens_are_not_written_again(
    session: Session, user: User, cipher: TokenCipher
) -> None:
    garmin = StubGarmin("stored-tokens")
    store_link(session, user.id, cipher, garmin)
    session.commit()
    stored = session.get_one(GarminLink, user.id).encrypted_tokens

    links.save_tokens(session, user.id, cipher, garmin)

    assert session.get_one(GarminLink, user.id).encrypted_tokens == stored
    assert not session.dirty


def test_only_one_sync_per_user_at_a_time(session: Session, user: User, db: Engine) -> None:
    other_user = uuid.uuid7()
    with links.sync_lock(session, user.id):
        with (
            make_session_factory(db)() as second,
            pytest.raises(AlreadySyncing),
            links.sync_lock(second, user.id),
        ):
            pass
        # Another user is not held up.
        with links.sync_lock(session, other_user):
            pass

    # Released when the sync ends.
    with links.sync_lock(session, user.id):
        pass


def test_a_lost_lock_connection_does_not_fail_the_sync(session: Session, user: User) -> None:
    with links.sync_lock(session, user.id):
        # The database closed the connection that holds the lock.
        session.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_locks "
                "WHERE locktype = 'advisory' AND pid <> pg_backend_pid()"
            )
        )
        session.commit()

    # Ending that connection released the lock.
    with links.sync_lock(session, user.id):
        pass


def test_user_without_a_link_cannot_be_opened(session: Session, cipher: TokenCipher) -> None:
    with pytest.raises(NotLinked):
        open_link(session, uuid.uuid7(), cipher)
