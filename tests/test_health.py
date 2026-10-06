import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.main import create_app


def test_liveness_does_not_require_database(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("checks", "expected_status"),
    [
        ({"database": True, "migrations": True, "pgvector": True}, 200),
        ({"database": True, "migrations": False, "pgvector": True}, 503),
        ({"database": True, "migrations": True, "pgvector": False}, 503),
    ],
)
def test_readiness_requires_migrations_and_pgvector(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    checks: dict[str, bool],
    expected_status: int,
) -> None:
    monkeypatch.setattr("app.api.health.database_checks", lambda engine, heads: checks)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == expected_status
    assert response.json()["checks"] == checks
    assert response.json()["status"] == ("ready" if expected_status == 200 else "not_ready")


def test_database_failure_is_sanitized(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "private-database-credentials"

    def unavailable(engine: object, heads: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception(secret))

    monkeypatch.setattr("app.api.health.database_checks", unavailable)
    with TestClient(create_app(settings)) as client, caplog.at_level(logging.WARNING):
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {
        "database": False,
        "migrations": False,
        "pgvector": False,
    }
    assert secret not in response.text
    assert secret not in caplog.text


def test_unreachable_database_returns_503(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
