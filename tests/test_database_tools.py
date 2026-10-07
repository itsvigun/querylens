from time import monotonic

import pytest

from app.config import AnalyticsSettings, Settings, SQLToolLimits
from app.tools.database import DatabaseTools
from app.tools.schema import get_database_schema


def reader_settings() -> AnalyticsSettings:
    return AnalyticsSettings(
        _env_file=None, ANALYTICS_READONLY_PASSWORD="offline-reader-password", postgres_port=1
    )


def test_schema_contains_only_reviewed_analytics_relations_and_no_credentials() -> None:
    schema = get_database_schema()
    assert {table["name"] for table in schema["tables"]} == {
        "users",
        "orders",
        "events",
        "subscriptions",
    }
    assert all(table["schema"] == "analytics" for table in schema["tables"])
    order = next(table for table in schema["tables"] if table["name"] == "orders")
    assert next(c for c in order["columns"] if c["name"] == "user_id")["references"] == [
        "analytics.users.id"
    ]
    assert next(c for c in order["columns"] if c["name"] == "created_at")["type"] == (
        "TIMESTAMP WITH TIME ZONE"
    )
    assert "password" not in str(schema).lower()


def test_owner_settings_cannot_be_used_for_the_sql_tool() -> None:
    with pytest.raises(ValueError, match="dedicated analytics"):
        DatabaseTools(Settings(_env_file=None, postgres_password="owner-secret"))


def test_rejection_and_expired_deadline_do_not_access_database(monkeypatch) -> None:
    with DatabaseTools(
        reader_settings(), SQLToolLimits(_env_file=None, sql_max_result_bytes=1024)
    ) as tools:

        def unexpected_connection():
            raise AssertionError("Rejected SQL must not reach PostgreSQL")

        monkeypatch.setattr(tools.engine, "connect", unexpected_connection)
        rejected = tools.execute_sql("DELETE FROM analytics.users")
        assert rejected.status == "rejected"
        assert rejected.error.category == "forbidden_sql"
        expired = tools.execute_sql("SELECT COUNT(*) FROM users", deadline=monotonic() - 1)
        assert expired.error.category == "deadline_exceeded"
        oversized = tools.execute_sql("SELECT '" + "x" * 2000 + "'")
        assert oversized.status == "rejected"


def test_unreachable_database_result_does_not_expose_credentials_or_driver_details(caplog) -> None:
    with DatabaseTools(reader_settings()) as tools:
        result = tools.execute_sql("SELECT COUNT(*) FROM users")
    assert result.status == "error"
    assert result.error.category == "database_unavailable"
    output = result.json_bytes().decode()
    assert "offline-reader-password" not in output + caplog.text
    assert "127.0.0.1" not in output
    assert result.rows == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"sql_max_rows": 1001},
        {"sql_max_result_bytes": 100},
        {"sql_statement_timeout_ms": 0},
        {"sql_tool_timeout_ms": 0},
    ],
)
def test_invalid_tool_limits_fail_before_execution(overrides) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SQLToolLimits(_env_file=None, **overrides)
