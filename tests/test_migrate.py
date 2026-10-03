from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from garmin_analyzer import migrate
from garmin_analyzer.models import Base


def test_upgrade_creates_the_schema(empty_db: Engine) -> None:
    assert not migrate.is_up_to_date(empty_db)

    migrate.upgrade(empty_db)

    assert migrate.is_up_to_date(empty_db)
    assert set(inspect(empty_db).get_table_names()) == {
        "alembic_version",
        "daily_summaries",
        "sleep_sessions",
        "heart_rate_samples",
        "stress_samples",
        "body_battery_samples",
        "respiration_samples",
        "hrv_summaries",
        "hrv_readings",
        "step_intervals",
        "training_readiness",
        "training_status",
        "vo2max",
        "race_predictions",
        "fitness_ages",
        "power_thresholds",
        "raw_files",
        "activities",
        "activity_laps",
        "activity_zones",
        "users",
        "sessions",
        "password_links",
        "garmin_links",
        "raw_payloads",
    }


def test_upgrade_is_repeatable(db: Engine) -> None:
    migrate.upgrade(db)

    assert migrate.is_up_to_date(db)


def test_migrations_match_the_models(db: Engine) -> None:
    """Fails when a model changed without a migration, or the other way round."""
    with db.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_downgrade_removes_everything(db: Engine) -> None:
    migrate.downgrade(db, "base")

    assert inspect(db).get_table_names() == ["alembic_version"]
    with db.connect() as connection:
        enum_types = connection.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
        assert enum_types.all() == []
