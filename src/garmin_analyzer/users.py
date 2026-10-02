"""Looking up and creating users."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from garmin_analyzer.models import User

# Not a valid hash of any password: the account cannot sign in until the web
# interface lets its owner set one.
NO_PASSWORD = "!"  # noqa: S105


class UserError(Exception):
    """The user does not exist, or already exists."""


def normalise_email(email: str) -> str:
    return email.strip().lower()


def find_user(session: Session, email: str) -> User:
    user = session.scalar(select(User).where(User.email == normalise_email(email)))
    if user is None:
        raise UserError(f"no user with email {normalise_email(email)}")
    return user


def add_user(session: Session, email: str) -> User:
    """Create a user. The first user of an instance becomes its administrator."""
    email = normalise_email(email)
    if "@" not in email:
        raise UserError(f"{email!r} is not an email address")
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise UserError(f"a user with email {email} already exists")
    is_first = session.scalar(select(func.count()).select_from(User)) == 0
    user = User(email=email, password_hash=NO_PASSWORD, is_admin=is_first)
    session.add(user)
    return user
