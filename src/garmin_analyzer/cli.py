"""Command-line entrypoint."""

import argparse
import os
import sys
from collections.abc import Sequence

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from garmin_analyzer import migrate
from garmin_analyzer.config import ConfigError
from garmin_analyzer.db import make_engine


def healthcheck(engine: Engine) -> int:
    """Check that the database answers and its schema is current."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    if not migrate.is_up_to_date(engine):
        print("database schema is not up to date, run: garmin-analyzer migrate", file=sys.stderr)
        return 1
    print("ok")
    return 0


def run_migrations(engine: Engine) -> int:
    migrate.upgrade(engine)
    print("database schema is up to date")
    return 0


COMMANDS = {
    "healthcheck": (healthcheck, "check that the database is reachable and migrated"),
    "migrate": (run_migrations, "apply database schema migrations"),
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="garmin-analyzer", description=__doc__)
    parser.add_argument(
        "--version",
        action="version",
        version=os.environ.get("GARMIN_ANALYZER_REVISION", "unknown"),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name, (_, description) in COMMANDS.items():
        subcommands.add_parser(name, help=description)
    args = parser.parse_args(argv)

    try:
        engine = make_engine()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        return COMMANDS[args.command][0](engine)
    except SQLAlchemyError as exc:
        print(f"database error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
