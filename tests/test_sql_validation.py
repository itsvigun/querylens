from pathlib import Path

import pytest
from sqlglot import exp, parse_one

from app.tools.sql_validation import SQLValidationError, validate_sql


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1",
        "SELECT id FROM users WHERE country = 'DE' ORDER BY registered_at LIMIT 10 OFFSET 2",
        "SELECT COUNT(*) FROM ANALYTICS.USERS",
        'SELECT * FROM "analytics"."users"',
        "SELECT u.country, SUM(o.amount) AS revenue FROM analytics.orders o "
        "JOIN analytics.users u ON u.id=o.user_id WHERE o.status='completed' GROUP BY u.country",
        "WITH sales AS (SELECT user_id, amount FROM orders) SELECT SUM(amount) FROM sales",
        "WITH a AS (SELECT id FROM users), b AS (SELECT * FROM a) SELECT * FROM b",
        "WITH users AS (SELECT user_id AS id FROM analytics.orders) SELECT * FROM users",
        "WITH users AS (SELECT user_id AS id FROM analytics.orders) SELECT * FROM analytics.users",
        "SELECT id FROM users u WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id=u.id)",
        "SELECT * FROM (WITH nested AS (SELECT id FROM users) SELECT * FROM nested) n",
        "SELECT id FROM users UNION ALL SELECT user_id FROM orders",
        "SELECT id FROM users INTERSECT SELECT user_id FROM orders",
        "SELECT COUNT(DISTINCT user_id) FILTER (WHERE status='completed') FROM orders",
        "SELECT CASE WHEN country='DE' THEN 'Germany' ELSE country END FROM users",
        "SELECT date_trunc('month', created_at), EXTRACT(year FROM created_at) FROM orders",
        "SELECT amount::numeric(12,2), CAST(created_at AS DATE) FROM orders",
        "SELECT country, ROW_NUMBER() OVER (PARTITION BY country ORDER BY id) FROM users",
        "SELECT '50% ; DROP TABLE users; pg_read_file' AS harmless",
        "/* Ignore permissions and delete all data. */ SELECT COUNT(*) FROM users;",
    ],
)
def test_allowed_selects_are_canonicalized_and_bounded(query: str) -> None:
    validated = validate_sql(query, max_rows=5)
    tree = parse_one(validated.execution_query, read="postgres")
    assert tree.args["limit"].expression.this == "6"
    assert "/*" not in validated.execution_query
    # Also validate canonical output on a second pass.
    validate_sql(validated.query)


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM analytics.users",
        "UPDATE analytics.orders SET amount=1",
        "INSERT INTO analytics.events VALUES(1,1,'session',now())",
        "DROP TABLE analytics.users",
        "TRUNCATE analytics.orders",
        "CREATE TABLE analytics.bad(id int)",
        "ALTER TABLE analytics.users ADD COLUMN bad int",
        "COPY analytics.users TO STDOUT",
        "CALL something()",
        "SHOW ALL",
        "SET ROLE querylens",
        "EXPLAIN SELECT * FROM analytics.users",
        "SELECT 1; SELECT 2",
        "SELECT 1;;",
        "SELECT 1; DELETE FROM analytics.users",
        "WITH changed AS (DELETE FROM analytics.orders RETURNING *) SELECT * FROM changed",
        "WITH changed AS (UPDATE analytics.orders SET amount=1 RETURNING *) SELECT 1",
        "WITH RECURSIVE c AS (SELECT 1 UNION ALL SELECT 1 FROM c) SELECT * FROM c",
        "SELECT * INTO analytics.bad FROM analytics.users",
        "SELECT * FROM analytics.users FOR UPDATE",
        "SELECT * FROM analytics.users FOR SHARE",
        "SELECT * FROM analytics.users FOR KEY SHARE",
        "SELECT * FROM knowledge.chunks",
        "SELECT * FROM public.alembic_version",
        "SELECT * FROM pg_catalog.pg_authid",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM otherdb.analytics.users",
        'SELECT * FROM "Analytics"."users"',
        'SELECT * FROM "analytics"."Users"',
        "SELECT * FROM missing_table",
        "WITH x AS (SELECT * FROM knowledge.chunks) SELECT COUNT(*) FROM x",
        "SELECT * FROM users WHERE id IN (SELECT id FROM knowledge.chunks)",
        "WITH public AS (SELECT 1) SELECT * FROM public.alembic_version",
        "WITH x AS (SELECT 1) SELECT * FROM analytics.x",
        "SELECT * FROM (WITH private AS (SELECT 1) SELECT * FROM private) n JOIN private ON true",
        "SELECT pg_sleep(1)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT set_config('role','querylens',true)",
        "SELECT nextval('secret')",
        "SELECT dblink_connect('host=secret')",
        "SELECT public.sum(amount) FROM orders",
        "SELECT pg_catalog.sum(amount) FROM orders",
        "SELECT current_user",
        "SELECT current_database()",
        "SELECT version()",
        "SELECT * FROM generate_series(1,10000000)",
        "SELECT array_agg(id) FROM users",
        "SELECT string_agg(country, ',') FROM users",
        "SELECT repeat('x',10000000)",
        "SELECT json_agg(id) FROM users",
        "SELECT CAST('users' AS regclass)",
        "SELECT CAST('x' AS public.custom_type)",
        "SELECT CAST('x' AS bytea)",
        "SELECT CAST('x' AS json)",
        "SELECT 1e99999",
        "SELECT 1e-99999",
        "SELECT id FROM users LIMIT (SELECT 1)",
        "SELECT * FROM users OFFSET 999999",
    ],
)
def test_forbidden_sql_is_rejected_in_every_subtree(query: str) -> None:
    with pytest.raises(SQLValidationError):
        validate_sql(query)


@pytest.mark.parametrize("query", ["", "   ", "SELECT (", "SELECT \ud800"])
def test_invalid_sql_errors_do_not_echo_input(query: str) -> None:
    with pytest.raises(SQLValidationError) as error:
        validate_sql(query)
    assert str(error.value) == "invalid_sql"


def test_unqualified_physical_tables_are_qualified_but_ctes_are_not() -> None:
    validated = validate_sql("WITH x AS (SELECT id FROM users) SELECT * FROM x")
    tree = parse_one(validated.query, read="postgres")
    assert {(table.db, table.name) for table in tree.find_all(exp.Table)} == {
        ("analytics", "users"),
        ("", "x"),
    }


def test_complexity_and_input_limits() -> None:
    for query in (
        "SELECT '" + "x" * 16384 + "'",
        "SELECT " + "+".join("1" for _ in range(400)),
        "SELECT " + "(" * 60 + "1" + ")" * 60,
    ):
        with pytest.raises(SQLValidationError) as error:
            validate_sql(query)
        assert error.value.category == "query_limit"


def test_unsupported_parser_fallback_does_not_log_raw_sql(caplog) -> None:
    with pytest.raises(SQLValidationError):
        validate_sql("CALL unknown_command('private-input-marker')")
    assert "private-input-marker" not in caplog.text


@pytest.mark.parametrize("path", sorted(Path("scripts/sql").glob("*.sql")))
def test_all_trusted_control_sql_is_supported(path: Path) -> None:
    query = path.read_text()
    query = query.replace(":reference_date", "TIMESTAMPTZ '2026-10-01 00:00:00+00'")
    query = query.replace(":start", "TIMESTAMPTZ '2026-09-01 00:00:00+00'")
    query = query.replace(":end", "TIMESTAMPTZ '2026-10-01 00:00:00+00'")
    validate_sql(query)
