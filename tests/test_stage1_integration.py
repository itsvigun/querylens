import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.config import AnalyticsSettings, Settings
from app.db.connection import create_database_engine
from app.db.schema import events, orders, subscriptions, users
from scripts.provision_roles import ANALYTICS_ROLE, KNOWLEDGE_ROLE, RolePasswords
from scripts.seed import database_fingerprint, generate_dataset, load_dataset
from scripts.verify_data import control_query, expected_report, query_report

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("QUERYLENS_INTEGRATION") != "1",
        reason="Requires migrations, provisioned roles, and the seeded demo database",
    ),
]


@pytest.fixture(scope="module")
def owner_engine():
    engine = create_database_engine(Settings())
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def reader_engine():
    settings = AnalyticsSettings()
    # Do not override role settings with connection options: verify PostgreSQL defaults.
    engine = create_engine(settings.database_url, hide_parameters=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def writer_engine():
    settings = Settings().model_copy(
        update={
            "postgres_user": KNOWLEDGE_ROLE,
            "postgres_password": RolePasswords().knowledge_writer_password,
        }
    )
    engine = create_engine(settings.database_url, hide_parameters=True)
    yield engine
    engine.dispose()


def test_control_queries_match_independent_reference_as_real_reader(reader_engine) -> None:
    with reader_engine.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        assert query_report(connection) == expected_report()


def test_repeat_seed_is_unchanged_and_differing_data_is_preserved(owner_engine) -> None:
    dataset = generate_dataset()
    assert load_dataset(owner_engine, dataset) == "unchanged"
    dataset["orders"][0]["amount"] += Decimal("0.01")
    with pytest.raises(ValueError, match="Existing analytics differs"):
        load_dataset(owner_engine, dataset)
    with owner_engine.connect() as connection:
        assert database_fingerprint(connection) == expected_report()["sha256"]


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO analytics.events VALUES (9999999, 1, 'session', now())",
        "UPDATE analytics.orders SET amount = 1 WHERE false",
        "DELETE FROM analytics.orders WHERE false",
        "TRUNCATE analytics.events",
        "CREATE TABLE analytics.forbidden (id int)",
        "CREATE TABLE public.forbidden (id int)",
        "CREATE TEMP TABLE forbidden (id int)",
        "ALTER TABLE analytics.users ADD COLUMN forbidden int",
        "SELECT * INTO analytics.forbidden FROM analytics.users LIMIT 1",
        "WITH d AS (DELETE FROM analytics.events WHERE false RETURNING *) SELECT * FROM d",
        "SET ROLE querylens",
        "SET ROLE querylens_knowledge_writer",
        "COPY analytics.users TO '/tmp/querylens-forbidden.csv'",
    ],
)
def test_reader_acl_rejects_writes_even_when_read_only_default_is_overridden(
    reader_engine, statement
) -> None:
    with reader_engine.connect() as connection:
        # A client can override the default; permissions must still block mutation.
        connection.execute(text("SET TRANSACTION READ WRITE"))
        with pytest.raises(DBAPIError) as error:
            connection.execute(text(statement))
        assert error.value.orig.pgcode == "42501"


def test_role_defaults_and_no_elevated_attributes(reader_engine, owner_engine) -> None:
    with reader_engine.connect() as connection:
        assert connection.scalar(text("SELECT current_user")) == ANALYTICS_ROLE
        assert connection.scalar(text("SHOW default_transaction_read_only")) == "on"
        assert connection.scalar(text("SHOW timezone")) == "UTC"
        assert connection.scalar(text("SHOW statement_timeout")) == "5s"
        assert connection.scalar(text("SHOW lock_timeout")) == "1s"
    with owner_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname IN "
                "('querylens_analytics_ro', 'querylens_knowledge_writer')"
            )
        ).all()
        assert len(rows) == 2
        assert all(not any(row) for row in rows)
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_auth_members WHERE member IN "
                    "(SELECT oid FROM pg_roles WHERE rolname IN "
                    "('querylens_analytics_ro', 'querylens_knowledge_writer'))"
                )
            )
            == 0
        )


def test_reader_statement_timeout_is_enforced_by_postgres(reader_engine) -> None:
    with reader_engine.connect() as connection:
        connection.execute(text("SET LOCAL statement_timeout = '50ms'"))
        with pytest.raises(DBAPIError) as error:
            connection.execute(text("SELECT pg_sleep(1)"))
        assert error.value.orig.pgcode == "57014"


def test_knowledge_writer_and_reader_are_isolated(
    owner_engine, writer_engine, reader_engine
) -> None:
    # A committed disposable relation checks default grants on future ingestion tables.
    probe = "probe_" + uuid4().hex
    with owner_engine.begin() as connection:
        connection.execute(
            text(f"CREATE TABLE knowledge.{probe} (id bigserial PRIMARY KEY, content text)")
        )
    try:
        with writer_engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        f"INSERT INTO knowledge.{probe} (content) VALUES ('synthetic') RETURNING id"
                    )
                )
                == 1
            )
            connection.execute(
                text(f"UPDATE knowledge.{probe} SET content = 'updated' WHERE id = 1")
            )
            assert connection.scalar(text(f"SELECT content FROM knowledge.{probe}")) == "updated"
            connection.execute(text(f"DELETE FROM knowledge.{probe} WHERE id = 1"))
        with reader_engine.connect() as connection:
            with pytest.raises(DBAPIError) as error:
                connection.execute(text(f"SELECT * FROM knowledge.{probe}"))
            assert error.value.orig.pgcode == "42501"
        for statement in (
            "SELECT * FROM analytics.users LIMIT 1",
            "INSERT INTO analytics.events VALUES (9999999, 1, 'session', now())",
            "CREATE TABLE knowledge.forbidden (id int)",
        ):
            with writer_engine.connect() as connection:
                with pytest.raises(DBAPIError) as error:
                    connection.execute(text(statement))
                assert error.value.orig.pgcode == "42501"
    finally:
        with owner_engine.begin() as connection:
            connection.execute(text(f"DROP TABLE knowledge.{probe}"))


def test_metric_boundaries_statuses_denominators_and_churn_cohort(owner_engine) -> None:
    # An isolated future period and rollback keep the versioned seed unchanged.
    start = datetime(2027, 1, 1, tzinfo=UTC)
    end = datetime(2027, 2, 1, tzinfo=UTC)
    with owner_engine.connect() as connection:
        connection.execute(
            users.insert(),
            [
                {
                    "id": i,
                    "country": "DE",
                    "registered_at": start - timedelta(days=1),
                    "status": "active",
                }
                for i in (10001, 10002)
            ],
        )
        connection.execute(
            orders.insert(),
            [
                {
                    "id": 20001 + i,
                    "user_id": 10001,
                    "amount": amount,
                    "currency": "EUR",
                    "created_at": timestamp,
                    "status": status,
                }
                for i, (timestamp, amount, status) in enumerate(
                    [
                        (start - timedelta(microseconds=1), Decimal("50"), "completed"),
                        (start, Decimal("100"), "completed"),
                        (end - timedelta(microseconds=1), Decimal("200"), "completed"),
                        (end, Decimal("400"), "completed"),
                        (start, Decimal("800"), "refunded"),
                        (start, Decimal("1600"), "cancelled"),
                    ]
                )
            ],
        )
        connection.execute(
            events.insert(),
            [
                {"id": 80001 + i, "user_id": user, "event_type": kind, "created_at": timestamp}
                for i, (user, kind, timestamp) in enumerate(
                    [
                        (10001, "session", start),
                        (10002, "session", end - timedelta(microseconds=1)),
                        (10002, "session", start),
                        (1, "session", end),
                        (2, "checkout", start),
                    ]
                )
            ],
        )
        row = connection.execute(control_query("period_metrics"), {"start": start, "end": end})
        assert dict(row.mappings().one()) == {
            "revenue": Decimal("300"),
            "completed_orders": 2,
            "paying_users": 1,
            "active_users": 2,
            "arpu": Decimal("150"),
            "arppu": Decimal("300"),
        }
        # Existing non-cancelled demo subscriptions also survive into this period.
        # Remove them only inside this rolled-back transaction to isolate the fixture.
        connection.execute(subscriptions.delete())
        connection.execute(
            subscriptions.insert(),
            [
                {
                    "id": 3001 + i,
                    "user_id": 10001,
                    "plan": "basic",
                    "started_at": started,
                    "cancelled_at": cancelled,
                }
                for i, (started, cancelled) in enumerate(
                    [
                        (start - timedelta(days=1), start),
                        (start - timedelta(days=1), end),
                        (start - timedelta(days=1), start - timedelta(microseconds=1)),
                        (start, start + timedelta(days=1)),
                    ]
                )
            ],
        )
        row = connection.execute(control_query("subscription_churn"), {"start": start, "end": end})
        assert dict(row.mappings().one()) == {
            "plan": "basic",
            "subscriptions_at_start": 2,
            "cancellations": 1,
            "churn_rate": Decimal("0.5"),
        }


def test_conversion_uses_individual_30_day_window_and_observation_cutoff(owner_engine) -> None:
    start = datetime(2027, 1, 1, tzinfo=UTC)
    end = datetime(2027, 2, 1, tzinfo=UTC)
    with owner_engine.connect() as connection:
        connection.execute(
            users.insert(),
            [
                {
                    "id": 10001 + i,
                    "country": "DE",
                    "registered_at": start + timedelta(days=i),
                    "status": "active",
                }
                for i in range(2)
            ],
        )
        connection.execute(
            orders.insert(),
            [
                {
                    "id": 20001 + i,
                    "user_id": 10001 + i,
                    "amount": Decimal("10"),
                    "currency": "EUR",
                    "created_at": timestamp,
                    "status": "completed",
                }
                for i, timestamp in enumerate([start, start + timedelta(days=31)])
            ],
        )
        parameters = {"start": start, "end": end, "reference_date": start + timedelta(days=31)}
        row = connection.execute(control_query("cohort_conversion"), parameters)
        assert dict(row.mappings().one()) == {
            "cohort_users": 2,
            "converted_users": 1,
            "fully_observed": True,
            "conversion_rate": Decimal("0.5"),
        }
        parameters["reference_date"] = start + timedelta(days=30)
        row = connection.execute(control_query("cohort_conversion"), parameters)
        assert dict(row.mappings().one()) == {
            "cohort_users": 2,
            "converted_users": 1,
            "fully_observed": False,
            "conversion_rate": None,
        }


def test_foreign_key_rejects_unknown_user(owner_engine) -> None:
    with owner_engine.connect() as connection:
        with pytest.raises(DBAPIError) as error:
            connection.execute(
                text("INSERT INTO analytics.events VALUES (9999999, 9999999, 'session', now())")
            )
        assert error.value.orig.pgcode == "23503"


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO analytics.orders VALUES (9999999, 1, -1, 'EUR', now(), 'completed')",
        "INSERT INTO analytics.orders VALUES (9999999, 1, 1, 'USD', now(), 'completed')",
        "INSERT INTO analytics.orders VALUES (9999999, 1, 1, 'EUR', now(), 'unknown')",
        "INSERT INTO analytics.subscriptions "
        "VALUES (9999999, 1, 'basic', now(), now() - interval '1 day')",
    ],
)
def test_database_constraints_reject_invalid_business_rows(owner_engine, statement) -> None:
    with owner_engine.connect() as connection:
        with pytest.raises(DBAPIError) as error:
            connection.execute(text(statement))
        assert error.value.orig.pgcode == "23514"
