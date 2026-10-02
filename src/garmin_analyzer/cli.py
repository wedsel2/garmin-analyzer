"""Command-line entrypoint."""

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from datetime import date, timedelta

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError

from garmin_analyzer import migrate
from garmin_analyzer.collector import collect_user
from garmin_analyzer.config import ConfigError, token_encryption_key
from garmin_analyzer.db import make_engine, make_session_factory
from garmin_analyzer.garmin import (
    SIGN_IN_URL,
    GarminError,
    GarminSession,
    LinkError,
    RelinkRequired,
)
from garmin_analyzer.links import NotLinked, store_link
from garmin_analyzer.models import GarminLink, LinkStatus, User
from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import UserError, add_user, find_user

DEFAULT_DAYS = 3


def healthcheck(engine: Engine, args: argparse.Namespace) -> int:
    """Check that the database answers and its schema is current."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    if not migrate.is_up_to_date(engine):
        print("database schema is not up to date, run: garmin-analyzer migrate", file=sys.stderr)
        return 1
    print("ok")
    return 0


def run_migrations(engine: Engine, args: argparse.Namespace) -> int:
    migrate.upgrade(engine)
    print("database schema is up to date")
    return 0


def user_add(engine: Engine, args: argparse.Namespace) -> int:
    with make_session_factory(engine)() as session:
        user = add_user(session, args.email)
        session.commit()
        role = "administrator" if user.is_admin else "user"
        print(f"created {role} {user.email}")
    return 0


def link(engine: Engine, args: argparse.Namespace) -> int:
    """Link a Garmin account: the user signs in in a browser, we get the ticket."""
    cipher = TokenCipher(token_encryption_key())
    with make_session_factory(engine)() as session:
        user = find_user(session, args.email)
        print("1. Open this address in your browser and sign in to Garmin:\n")
        print(f"   {SIGN_IN_URL}\n")
        print("2. Copy the full address shown after signing in (it contains")
        print("   ticket=ST-...) and paste it here within a minute.\n")
        garmin = GarminSession.from_ticket(input("Address: "))
        store_link(session, user.id, cipher, garmin)
        session.commit()
        print(f"linked Garmin for {user.email}")
    return 0


def collect(engine: Engine, args: argparse.Namespace) -> int:
    cipher = TokenCipher(token_encryption_key())
    today = date.today()
    since = args.since or today - timedelta(days=args.days - 1)
    failed = False
    with make_session_factory(engine)() as session:
        if args.email:
            users = [find_user(session, args.email)]
        else:
            users = list(
                session.scalars(
                    select(User)
                    .join(GarminLink, GarminLink.user_id == User.id)
                    .where(GarminLink.status == LinkStatus.ACTIVE)
                    .order_by(User.email)
                )
            )
        for user in users:
            try:
                result = collect_user(session, user.id, cipher, since, today, args.pause)
            except (NotLinked, RelinkRequired, GarminError) as error:
                print(f"{user.email}: {error}", file=sys.stderr)
                failed = True
                continue
            print(
                f"{user.email}: {since} to {today}, {result.calls} requests, "
                f"{result.rows} rows, {len(result.errors)} failed requests"
            )
            for failure in result.errors:
                print(f"  failed: {failure}", file=sys.stderr)
            if result.stopped:
                print(f"  stopped early: {result.stopped}", file=sys.stderr)
                failed = True
    return 1 if failed else 0


Handler = Callable[[Engine, argparse.Namespace], int]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="garmin-analyzer", description=__doc__)
    parser.add_argument(
        "--version",
        action="version",
        version=os.environ.get("GARMIN_ANALYZER_REVISION", "unknown"),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler: Handler | None, description: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=description)
        command.set_defaults(handler=handler)
        return command

    add("healthcheck", healthcheck, "check that the database is reachable and migrated")
    add("migrate", run_migrations, "apply database schema migrations")
    add("generate-key", None, "print a new TOKEN_ENCRYPTION_KEY")
    add("user-add", user_add, "create a user").add_argument("email")
    add("link", link, "link a user to their Garmin account").add_argument("email")
    collector = add("collect", collect, "fetch Garmin data for one user or all linked users")
    collector.add_argument("email", nargs="?", help="default: every user with an active link")
    collector.add_argument(
        "--days", type=int, default=DEFAULT_DAYS, help="days back from today (default: 3)"
    )
    collector.add_argument(
        "--since", type=date.fromisoformat, help="first day to fetch, as YYYY-MM-DD"
    )
    collector.add_argument(
        "--pause", type=float, default=1.0, help="seconds between requests (default: 1)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.handler is None:
        print(generate_key())
        return 0

    try:
        engine = make_engine()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        code: int = args.handler(engine, args)
        return code
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    except (UserError, LinkError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        print(f"database error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
