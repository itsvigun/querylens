# Validated SQL tool

[Documentation index](README.md)

`get_database_schema()` exposes reviewed SQLAlchemy metadata: four analytics
tables, PostgreSQL types, keys, constraints, and the demo time anchor. It does not
discover arbitrary database catalogs or confirm that migrations/data are loaded.
Use `alembic check` to detect schema drift.

After migrations, role provisioning, and seed, inspect metadata and run SQL:

```bash
uv run --locked python -m scripts.query --schema
printf '%s\n' "SELECT COUNT(*) AS users FROM analytics.users" \
  | uv run --locked python -m scripts.query

# The Docker job uses the same tool. Disable TTY allocation for stdin.
docker compose run --rm query python -m scripts.query --schema
printf '%s\n' "SELECT COUNT(*) AS users FROM analytics.users" \
  | docker compose run --rm -T query
```

The count query returns an actual database value of 10000 for synthetic-v1.
`scripts.query` prints compact JSON and exits with code 1 for rejection/error.
These are backend tools and a local CLI; chat uses them through validated LLM dispatch.

The policy validates every AST node and lexical relation scope. It accepts one
SELECT, nonrecursive read CTEs, nested/correlated queries, joins, aggregates,
set operations, and a limited set of window/date/string functions. Physical
tables are qualified to `analytics`. Writes (including unused write CTEs), DDL,
COPY, SELECT INTO, locking, extra statements, recursive CTEs, knowledge/catalog
relations, qualified or unapproved functions, and unapproved casts are rejected.
Comments are removed. Input is limited to 16 KiB, 600 AST nodes, and depth 40.
Exact reviewed node/function/type allowlists live in
[sql_validation.py](../app/tools/sql_validation.py). SQLGlot is pinned because parser
acceptance alone is not a security policy; upgrades require policy review/tests.
Valid PostgreSQL outside this deliberately small subset may be rejected.

`DatabaseTools.execute_sql()` creates a server-controlled read-only transaction
using only `querylens_analytics_ro`, verifies that identity and read-only state,
and sets `search_path=pg_catalog`, UTC, and standard string escaping. Only the
SQL regenerated from the validated AST is executed. A top-level AST LIMIT caps
fetching to the row limit plus one sentinel; smaller user limits and ordering are
preserved. A named cursor fetches batches of 16, with at most 64 result columns.

Results include status, the actual bounded SQL, column names/types, row arrays,
row count, elapsed milliseconds, and explicit truncation reasons (`row_limit`
or `byte_limit`). Byte limits include SQL and metadata; only whole rows are kept.
A response whose SQL/metadata cannot fit fails with `result_limit`. An oversized
first value yields zero rows with explicit byte truncation. Duplicate column names
are preserved because rows are arrays. Decimal money and integers beyond
JavaScript's exact range are strings; dates/timestamps use ISO format. Errors
return safe categories/messages and discard partial rows and database details.

Statement timeouts are shortened to the remaining tool/caller budget before
executing and before each fetch. Expired budgets fail explicitly; failures roll
back and the reader pool supports subsequent queries. This is a cooperative
deadline, not a hard network wall-clock guarantee: libpq connection timeout has
second granularity, and a stalled network operation can outlast the budget.
Result limits bound returned JSON, not PostgreSQL intermediate work or the size
of a single driver fetch. Expensive queries still require runtime timeouts. The
chat workflow also enforces a request deadline, SQL repair/tool/model budgets,
and one active chat per process; see the [chat guide](chat.md).
