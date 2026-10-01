"""Alembic environment. Run through garmin_analyzer.migrate or the alembic CLI."""

from alembic import context
from sqlalchemy import Connection

from garmin_analyzer.db import make_engine
from garmin_analyzer.models import Base


def run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


# The application passes its own connection; the alembic CLI does not.
supplied: Connection | None = context.config.attributes.get("connection")
if supplied is not None:
    run(supplied)
else:
    engine = make_engine()
    with engine.begin() as own_connection:
        run(own_connection)
    engine.dispose()
