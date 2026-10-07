from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.config import AnalyticsSettings, Settings


def test_password_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_password_is_hidden_and_url_handles_reserved_characters(settings: Settings) -> None:
    password = "secret:@/%?#"
    settings.postgres_password = type(settings.postgres_password)(password)
    assert password not in repr(settings)
    assert password not in str(settings.database_url)
    assert (
        make_url(settings.database_url.render_as_string(hide_password=False)).password == password
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"postgres_password": ""},
        {"postgres_port": 0},
        {"db_connect_timeout_seconds": 0},
        {"db_statement_timeout_ms": 0},
    ],
)
def test_invalid_database_settings_are_rejected(overrides: dict[str, str | int]) -> None:
    values = {"postgres_password": "test-password", **overrides}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_environment_overrides_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("POSTGRES_HOST=127.0.0.1\nPOSTGRES_PASSWORD=test-only\nAPI_PORT=8000\n")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    settings = Settings(_env_file=dotenv)
    assert settings.postgres_host == "db"


def test_reader_settings_cannot_fall_back_to_owner_credentials(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "querylens")
    monkeypatch.setenv("POSTGRES_PASSWORD", "owner-only-password")
    monkeypatch.delenv("ANALYTICS_READONLY_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        AnalyticsSettings(_env_file=None)
    monkeypatch.setenv("ANALYTICS_READONLY_PASSWORD", "dedicated-reader-password")
    settings = AnalyticsSettings(_env_file=None)
    assert settings.database_url.username == "querylens_analytics_ro"
    assert settings.database_url.password == "dedicated-reader-password"
