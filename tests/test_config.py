import pytest

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
