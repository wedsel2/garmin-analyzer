"""Command-line entrypoint."""

import argparse
import os
import sys
from collections.abc import Sequence

import psycopg


def check_database(dsn: str) -> None:
    """Raise psycopg.Error if the database does not answer a trivial query."""
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SELECT 1")


def healthcheck() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    try:
        check_database(dsn)
    except psycopg.Error as exc:
        print(f"database unreachable: {exc}", file=sys.stderr)
        return 1
    print("ok")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="garmin-analyzer", description=__doc__)
    parser.add_argument(
        "--version",
        action="version",
        version=os.environ.get("GARMIN_ANALYZER_REVISION", "unknown"),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("healthcheck", help="check that the database is reachable")
    parser.parse_args(argv)
    return healthcheck()
