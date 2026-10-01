import pytest
from sqlalchemy import Engine

from garmin_analyzer import cli, migrate


def test_healthcheck_ok_on_migrated_database(
    db: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["healthcheck"]) == 0
    assert capsys.readouterr().out == "ok\n"


def test_healthcheck_fails_when_schema_is_behind(
    empty_db: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["healthcheck"]) == 1
    assert "database schema is not up to date" in capsys.readouterr().err


def test_healthcheck_fails_when_database_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@127.0.0.1:1/name")

    assert cli.main(["healthcheck"]) == 1
    assert "database error" in capsys.readouterr().err


def test_migrate_brings_schema_up_to_date(
    empty_db: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["migrate"]) == 0
    assert capsys.readouterr().out == "database schema is up to date\n"
    assert migrate.is_up_to_date(empty_db)


def test_database_url_is_required(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert cli.main(["healthcheck"]) == 2
    assert "DATABASE_URL is not set" in capsys.readouterr().err


def test_version_prints_revision(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GARMIN_ANALYZER_REVISION", "abc123")

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == "abc123\n"


def test_command_is_required() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])

    assert exit_info.value.code == 2
