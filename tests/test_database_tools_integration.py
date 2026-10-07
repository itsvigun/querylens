"""Exercise the complete validated tool against the provisioned demo PostgreSQL."""

import os
from decimal import Decimal
from pathlib import Path
from time import monotonic

import pytest
from sqlalchemy import event

from app.config import Settings, SQLToolLimits
from app.db.connection import create_database_engine
from app.demo import REFERENCE_DATE
from app.tools.database import DatabaseTools
from scripts.reference_metrics import PERIODS, normalize_metrics
from scripts.verify_data import expected_report

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("QUERYLENS_INTEGRATION") != "1",
        reason="Requires the migrated, provisioned, seeded demo PostgreSQL",
    ),
]


@pytest.fixture(scope="module")
def tools():
    with DatabaseTools(limits=SQLToolLimits(_env_file=None)) as instance:
        yield instance


def result_records(result):
    assert result.status == "ok", result.model_dump()
    assert not result.truncated
    names = [column.name for column in result.columns]
    numeric = {column.name for column in result.columns if column.type == "numeric"}
    return [
        normalize_metrics(
            {
                name: Decimal(value) if name in numeric and value is not None else value
                for name, value in zip(names, row, strict=True)
            }
        )
        for row in result.rows
    ]


@pytest.mark.parametrize(
    "query_name,period,key",
    [("period_metrics", period, "periods") for period in PERIODS]
    + [("country_revenue", period, "country_revenue") for period in ("august", "september")]
    + [("subscription_churn", "september", "september_churn")]
    + [
        ("cohort_conversion", period, "conversion")
        for period in ("august", "september", "empty_june")
    ],
)
def test_control_queries_through_tool_match_independent_values(tools, query_name, period, key):
    start, end = PERIODS[period]
    query = (Path("scripts/sql") / f"{query_name}.sql").read_text()
    for name, value in {"start": start, "end": end, "reference_date": REFERENCE_DATE}.items():
        query = query.replace(f":{name}", f"TIMESTAMPTZ '{value.isoformat()}'")
    actual = result_records(tools.execute_sql(query))
    expected = expected_report()[key]
    if key in {"periods", "conversion"}:
        assert actual == [expected[period]]
    elif key == "country_revenue":
        assert actual == expected[period]
    else:
        assert actual == expected


def test_values_and_duplicate_column_names_are_preserved(tools):
    result = tools.execute_sql(
        "SELECT '50% ; DELETE FROM users' AS value, 'Привіт' AS value, "
        "CAST(1.20 AS numeric(12,2)) AS money, "
        "TIMESTAMPTZ '2026-10-01 00:00:00+00' AS time, "
        "CAST('9007199254740993' AS bigint) AS large_integer, NULL AS absent"
    )
    assert result.status == "ok"
    assert [c.name for c in result.columns][:2] == ["value", "value"]
    assert result.rows == [
        [
            "50% ; DELETE FROM users",
            "Привіт",
            "1.20",
            "2026-10-01T00:00:00+00:00",
            "9007199254740993",
            None,
        ]
    ]
    assert not result.truncated


@pytest.mark.parametrize(
    "suffix,rows,truncated",
    [
        ("", [[1], [2], [3]], True),
        (" LIMIT 2", [[1], [2]], False),
        (" LIMIT 3", [[1], [2], [3]], False),
        (" LIMIT 0", [], False),
        (" LIMIT 2 OFFSET 4", [[5], [6]], False),
    ],
)
def test_row_limits_preserve_order_and_smaller_user_limits(suffix, rows, truncated):
    with DatabaseTools(limits=SQLToolLimits(_env_file=None, sql_max_rows=3)) as instance:
        result = instance.execute_sql("SELECT ID FROM ANALYTICS.USERS ORDER BY ID" + suffix)
    assert result.status == "ok", result.model_dump()
    assert result.rows == rows
    assert result.row_count == len(rows)
    assert result.truncated == truncated
    assert result.truncation_reasons == (["row_limit"] if truncated else [])


def test_byte_limit_counts_entire_utf8_json_and_keeps_whole_rows():
    limits = SQLToolLimits(_env_file=None, sql_max_result_bytes=1024)
    with DatabaseTools(limits=limits) as instance:
        result = instance.execute_sql(
            "SELECT id, 'Привіт \"quoted\"' AS label FROM users ORDER BY id"
        )
        oversized_cell = instance.execute_sql("SELECT CAST(CAST('1e5000' AS numeric) AS text)")
    for output in (result, oversized_cell):
        assert output.status == "ok", output.model_dump()
        assert output.truncation_reasons == ["byte_limit"]
        assert output.truncated
        assert len(output.json_bytes()) <= limits.sql_max_result_bytes
        assert output.row_count == len(output.rows)
    assert 0 < result.row_count < 1000
    assert all(len(row) == 2 and row[1] == 'Привіт "quoted"' for row in result.rows)
    assert oversized_cell.rows == []


@pytest.mark.parametrize("budget", [1024, 4096, 65536])
def test_response_budget_at_different_sizes(budget):
    with DatabaseTools(
        limits=SQLToolLimits(_env_file=None, sql_max_result_bytes=budget)
    ) as instance:
        result = instance.execute_sql("SELECT id, country FROM users ORDER BY id")
    assert result.status == "ok"
    assert len(result.json_bytes()) <= budget
    assert result.row_count == len(result.rows)
    assert result.rows == [[i, row[1]] for i, row in enumerate(result.rows, start=1)]
    assert result.truncation_reasons == (["row_limit"] if budget == 65536 else ["byte_limit"])


def test_string_escapes_cannot_change_statement_structure(tools):
    result = tools.execute_sql("SELECT 'a\\b''; DELETE FROM users; --' AS harmless")
    assert result.status == "ok", result.model_dump()
    assert result.rows == [["a\\b'; DELETE FROM users; --"]]
    assert tools.execute_sql("SELECT COUNT(*) FROM users").rows == [[10000]]


def test_column_limit_and_empty_results(tools):
    too_many = tools.execute_sql("SELECT " + ",".join(f"1 AS col{i}" for i in range(65)))
    assert too_many.error.category == "result_limit"
    assert too_many.rows == []
    empty = tools.execute_sql("SELECT id FROM users WHERE id < 0")
    assert empty.status == "ok"
    assert [c.name for c in empty.columns] == ["id"]
    assert empty.rows == []
    assert not empty.truncated


def test_database_errors_are_sanitized_and_next_query_recovers(tools):
    for query, category in [
        ("SELECT private_column_marker FROM users", "unknown_column"),
        ("SELECT 1 / 0", "database_error"),
        ("SELECT CAST('NaN' AS numeric)", "result_format"),
    ]:
        failed = tools.execute_sql(query)
        assert failed.error.category == category
        assert failed.executed_sql is None
        assert failed.rows == []
        assert "private_column_marker" not in failed.json_bytes().decode()
        assert tools.execute_sql("SELECT COUNT(*) FROM users").rows == [[10000]]


def test_server_controls_transaction_and_search_path(tools):
    observed = []

    def inspect_transaction(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT current_user"):
            with connection.connection.driver_connection.cursor() as probe:
                probe.execute(
                    "SELECT current_setting('transaction_read_only'), "
                    "current_setting('search_path'), current_setting('TimeZone')"
                )
                observed.append(probe.fetchone())

    event.listen(tools.engine, "after_cursor_execute", inspect_transaction)
    try:
        assert tools.execute_sql("SELECT COUNT(*) FROM users").rows == [[10000]]
    finally:
        event.remove(tools.engine, "after_cursor_execute", inspect_transaction)
    assert observed == [("on", "pg_catalog", "UTC")]


def test_runtime_guard_refuses_an_accidentally_substituted_owner_engine():
    owner_engine = create_database_engine(Settings())
    with DatabaseTools() as instance:
        reader_engine = instance.engine
        instance.engine = owner_engine
        try:
            result = instance.execute_sql("SELECT COUNT(*) FROM users")
            assert result.error.category == "database_error"
            assert result.rows == []
        finally:
            instance.engine = reader_engine
            owner_engine.dispose()


EXPENSIVE_QUERY = "SELECT COUNT(*) FROM users a CROSS JOIN users b CROSS JOIN users c"


def test_real_statement_timeout_and_pool_recovery():
    with DatabaseTools(
        limits=SQLToolLimits(_env_file=None, sql_statement_timeout_ms=50, sql_tool_timeout_ms=2000)
    ) as instance:
        assert instance.execute_sql("SELECT 1").status == "ok"
        result = instance.execute_sql(EXPENSIVE_QUERY)
        assert result.status == "error"
        assert result.error.category == "timeout"
        assert result.rows == []
        assert instance.execute_sql("SELECT COUNT(*) FROM users").rows == [[10000]]


def test_caller_deadline_shortens_statement_timeout():
    with DatabaseTools(limits=SQLToolLimits(_env_file=None)) as instance:
        assert instance.execute_sql("SELECT 1").status == "ok"
        result = instance.execute_sql(EXPENSIVE_QUERY, deadline=monotonic() + 0.2)
        assert result.error.category == "deadline_exceeded"
        assert result.rows == []
        assert instance.execute_sql("SELECT COUNT(*) FROM users").rows == [[10000]]


def test_real_lock_timeout_and_recovery(tools):
    owner_engine = create_database_engine(Settings())
    try:
        with owner_engine.connect() as connection, connection.begin():
            connection.exec_driver_sql("LOCK TABLE analytics.orders IN ACCESS EXCLUSIVE MODE")
            result = tools.execute_sql("SELECT COUNT(*) FROM orders")
            assert result.error.category == "timeout"
            assert result.rows == []
        assert tools.execute_sql("SELECT COUNT(*) FROM orders").rows == [[20000]]
    finally:
        owner_engine.dispose()
