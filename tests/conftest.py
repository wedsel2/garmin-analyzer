import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from testcontainers.community.postgres import PostgresContainer

from garmin_analyzer import migrate
from garmin_analyzer.db import make_engine

COMPOSE_FILE = Path(__file__).parent.parent / "compose.yaml"


def postgres_image() -> str:
    """Test against the same PostgreSQL image the compose stack runs."""
    match = re.search(r"image:\s*(postgres:\S+)", COMPOSE_FILE.read_text(encoding="utf-8"))
    if match is None:
        raise RuntimeError("no postgres image found in compose.yaml")
    return match.group(1)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A plain postgresql:// URL, as a deployment would set DATABASE_URL."""
    with PostgresContainer(postgres_image(), driver=None) as postgres:
        yield postgres.get_connection_url()


@pytest.fixture
def empty_db(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """An engine on a database with no tables; DATABASE_URL points at it."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    engine = make_engine()
    with engine.begin() as connection:
        # Fail fast instead of hanging if a test left a transaction open.
        connection.execute(text("SET lock_timeout = '10s'"))
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    yield engine
    engine.dispose()


@pytest.fixture
def db(empty_db: Engine) -> Engine:
    """An engine on a fully migrated database."""
    migrate.upgrade(empty_db)
    return empty_db
