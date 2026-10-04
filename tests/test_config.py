import pytest

from garmin_analyzer import config
from garmin_analyzer.config import ConfigError, database_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("postgresql://u:p@db:5432/name", "postgresql+psycopg://u:p@db:5432/name"),
        ("postgres://u:p@db/name", "postgresql+psycopg://u:p@db/name"),
        ("postgresql+psycopg://u:p@db/name", "postgresql+psycopg://u:p@db/name"),
    ],
)
def test_database_url_selects_psycopg_driver(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", value)

    assert database_url() == expected


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigError, match="DATABASE_URL is not set"):
        database_url()


def test_the_coach_has_defaults_and_can_be_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "COACH_MODEL", "COACH_REPORTS_PER_DAY"):
        monkeypatch.setenv(name, " ")

    assert config.anthropic_api_key() is None
    assert config.coach_model() == "claude-opus-5-5"
    assert config.coach_reports_per_day() == 3

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-of-the-instance")
    monkeypatch.setenv("COACH_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("COACH_REPORTS_PER_DAY", "10")

    assert config.anthropic_api_key() == "sk-ant-of-the-instance"
    assert config.coach_model() == "claude-sonnet-5-5"
    assert config.coach_reports_per_day() == 10


@pytest.mark.parametrize("value", ["many", "0", "-1", "2.5"])
def test_a_number_of_reports_that_is_not_one_is_refused(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("COACH_REPORTS_PER_DAY", value)

    with pytest.raises(ConfigError, match="COACH_REPORTS_PER_DAY"):
        config.coach_reports_per_day()
