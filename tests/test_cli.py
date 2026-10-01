from unittest.mock import MagicMock

import psycopg
import pytest

from garmin_analyzer import cli

DSN = "postgresql://user@db/name"


def test_healthcheck_ok(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    connect = MagicMock()
    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setenv("DATABASE_URL", DSN)

    assert cli.main(["healthcheck"]) == 0
    assert capsys.readouterr().out == "ok\n"
    connect.assert_called_once_with(DSN, connect_timeout=5)
    connect.return_value.__enter__.return_value.execute.assert_called_once_with("SELECT 1")


def test_healthcheck_database_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(psycopg, "connect", MagicMock(side_effect=psycopg.OperationalError("down")))
    monkeypatch.setenv("DATABASE_URL", DSN)

    assert cli.main(["healthcheck"]) == 1
    assert "database unreachable: down" in capsys.readouterr().err


def test_healthcheck_requires_database_url(
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
