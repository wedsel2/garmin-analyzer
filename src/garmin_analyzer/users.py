"""Looking up and creating users."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from garmin_analyzer.models import PasswordLink, User
from garmin_analyzer.passwords import hash_password
from garmin_analyzer.sessions import end_sessions_of

# Not a valid hash of any password: the account cannot sign in until the web
# interface lets its owner set one.
NO_PASSWORD = "!"  # noqa: S105
MAX_NAME_LENGTH = 100


class UserError(Exception):
    """The user does not exist, or already exists."""


def normalise_email(email: str) -> str:
    return email.strip().lower()


def find_user(session: Session, email: str) -> User:
    user = session.scalar(select(User).where(User.email == normalise_email(email)))
    if user is None:
        raise UserError(f"no user with email {normalise_email(email)}")
    return user


def check_new_email(session: Session, email: str) -> None:
    """Refuse an address that is not one, or that an account already has."""
    if "@" not in email:
        raise UserError(f"{email!r} is not an email address")
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise UserError(f"a user with email {email} already exists")


def add_user(session: Session, email: str) -> User:
    """Create a user. The first user of an instance becomes its administrator."""
    email = normalise_email(email)
    check_new_email(session, email)
    is_first = session.scalar(select(func.count()).select_from(User)) == 0
    user = User(email=email, password_hash=NO_PASSWORD, is_admin=is_first)
    session.add(user)
    return user


def change_email(session: Session, user: User, email: str) -> None:
    """Give a user another address to sign in with."""
    email = normalise_email(email)
    if email != user.email:
        check_new_email(session, email)
        user.email = email


def set_name(user: User, name: str) -> None:
    """Set what the user is called; a blank name removes it."""
    user.name = name.strip()[:MAX_NAME_LENGTH] or None


def set_password(session: Session, user: User, password: str) -> None:
    """Give a user a new password, sign them out everywhere and cancel their password link."""
    user.password_hash = hash_password(password)
    end_sessions_of(session, user.id)
    # A link made earlier must not be able to replace this password.
    session.execute(delete(PasswordLink).where(PasswordLink.user_id == user.id))
