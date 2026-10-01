"""Apply and inspect schema migrations from inside the application."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

MIGRATIONS = Path(__file__).parent / "migrations"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    return config


def upgrade(engine: Engine, revision: str = "head") -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def downgrade(engine: Engine, revision: str) -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, revision)


def is_up_to_date(engine: Engine) -> bool:
    """True when the database is at the newest migration."""
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision() == head
