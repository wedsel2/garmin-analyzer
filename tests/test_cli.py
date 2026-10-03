from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine

from garmin_analyzer import cli, migrate
from garmin_analyzer.tokens import TokenCipher


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


def test_generate_key_needs_no_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert cli.main(["generate-key"]) == 0
    TokenCipher(capsys.readouterr().out.strip())


def test_serve_migrates_and_then_runs_the_web_interface(
    empty_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: dict[str, Any] = {}

    def run(app: FastAPI, **options: Any) -> None:
        started.update(options, title=app.title, migrated=migrate.is_up_to_date(empty_db))

    monkeypatch.setattr("uvicorn.run", run)

    assert cli.main(["serve", "--port", "8123"]) == 0
    assert started == {
        "title": "Garmin Analyzer",
        "migrated": True,
        "host": "127.0.0.1",
        "port": 8123,
        "proxy_headers": True,
    }


@pytest.mark.parametrize(
    "command",
    [["user-add", "runner@example.com"], ["user-password", "runner@example.com"], ["collect"]],
)
def test_commands_that_use_tables_ask_for_migrations_first(
    empty_db: Engine, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    migrate.upgrade(empty_db, "0007")

    assert cli.main(command) == 1
    assert capsys.readouterr().err == (
        "database schema is not up to date, run: garmin-analyzer migrate\n"
    )
