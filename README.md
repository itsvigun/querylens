# QueryLens

QueryLens is being built to answer business questions using documentation
retrieval, LLM tool calling, and read-only SQL over synthetic PostgreSQL data.

**Current status: stage 3 — documentation ingestion and retrieval; live verification pending.**
The API foundation, analytics schema, dedicated database roles, reproducible seed,
control SQL, reviewed schema metadata, SQL execution tool, and embedding/retrieval
commands are implemented. Offline and PostgreSQL checks pass; live OpenAI retrieval
verification is pending an API key. LLM tool calling and a demo UI come next.
The API foundation and tests need no API key; real ingestion/search do.

## Stack

- Python 3.14.8 and uv with dependencies pinned in `uv.lock`.
- FastAPI and Uvicorn.
- SQLAlchemy 2.0 and psycopg2 for PostgreSQL connections.
- Alembic for explicit database migrations.
- SQLGlot 30.21.0 for a fail-closed PostgreSQL AST policy.
- OpenAI SDK 3.26.0 for embeddings and pgvector Python 0.5.0 for vector SQLAlchemy types.
- PostgreSQL 17 with pgvector 0.8.6, running in Docker Compose.
- pytest, HTTPX2, and Ruff for local checks.

Database health checks are synchronous FastAPI endpoints, executed in its worker
thread pool. The database engine is created during application lifespan and
disposed on shutdown. Startup does not connect to the database or run migrations.

## Quickstart with Docker

Prerequisites: Git and Docker with Compose v2 or later. Docker Desktop must be
running on macOS. The first build needs access to Docker Hub, GHCR, and PyPI.

```bash
git clone git@github.com:itsvigun/querylens.git
cd querylens
cp .env.example .env
```

Set `POSTGRES_PASSWORD`, `ANALYTICS_READONLY_PASSWORD`,
`KNOWLEDGE_WRITER_PASSWORD`, and `KNOWLEDGE_READONLY_PASSWORD` in `.env` to distinct
local passwords. Dedicated-role passwords must have at least 16 characters.
Example values are placeholders.
`.env` is excluded from Git and the Docker build context.

Start the database, apply migrations, provision roles, load and verify data,
then start the API. Administration commands are explicit jobs:

```bash
docker compose up -d --wait db
docker compose run --build --rm migrate
docker compose run --rm provision-roles
docker compose run --rm seed
docker compose run --rm verify-data
docker compose up --build -d --wait api
```

Open [interactive API documentation](http://127.0.0.1:8000/docs) or check health:

```bash
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
curl --fail http://127.0.0.1:8000/demo
```

Expected responses:

```json
{"status":"ok"}
```

```json
{"status":"ready","checks":{"database":true,"migrations":true,"pgvector":true}}
```

Inspect or stop the services:

```bash
docker compose ps
docker compose logs api
docker compose down
```

The named `postgres_data` volume survives `docker compose down` and service
restarts. Changing the password in `.env` does not change the password of an
already initialized database; update the database role password too if needed.

## Local Python development

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.12.23 or later.
uv selects Python 3.14.8 using `.python-version` and downloads it when necessary.
Follow the environment setup above, then run:

```bash
uv sync --locked
docker compose up -d --wait db
uv run --locked alembic upgrade head
uv run --locked python -m scripts.provision_roles
uv run --locked python -m scripts.seed
uv run --locked python -m scripts.verify_data
docker compose stop api
uv run --locked uvicorn app.main:app --reload
```

Host-side Python connects to `127.0.0.1:5433`; container services connect to
`db:5432`. Compose overrides the database host and port for the API and migration
service. The API is available on port 8000 by default. `API_PORT` configures the
Compose host port; pass `--port` to Uvicorn when changing it during local development.

Both published Docker ports bind to loopback. If ports are already occupied,
change `POSTGRES_PORT` or `API_PORT` in `.env`.

## Configuration

Settings load from `.env`, with environment variables taking precedence. Unknown
dotenv keys are ignored so Compose-only settings can share the same file.

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_USER` | `querylens` | Local database owner |
| `POSTGRES_PASSWORD` | Required | Local database password, represented as a secret |
| `POSTGRES_DB` | `querylens` | Database name |
| `POSTGRES_HOST` | `127.0.0.1` | Host for local Python commands |
| `POSTGRES_PORT` | `5433` | Host database port |
| `API_PORT` | `8000` | Compose host API port |
| `DB_CONNECT_TIMEOUT_SECONDS` | `3` | Connection and pool acquisition timeout |
| `DB_STATEMENT_TIMEOUT_MS` | `5000` | PostgreSQL per-statement timeout |
| `ANALYTICS_READONLY_PASSWORD` | Required for provisioning/verification/SQL tool | Dedicated reader password; never falls back to owner credentials |
| `KNOWLEDGE_WRITER_PASSWORD` | Required for provisioning | Dedicated ingestion writer password |
| `KNOWLEDGE_READONLY_PASSWORD` | Required for provisioning/search | Dedicated knowledge reader password |
| `SQL_MAX_ROWS` | `1000` | SQL response row limit, configurable from 1 to 1000 |
| `SQL_MAX_RESULT_BYTES` | `65536` | Entire compact UTF-8 JSON response budget, from 1024 to 1048576 bytes |
| `SQL_STATEMENT_TIMEOUT_MS` | `5000` | SQL statement/fetch timeout, from 10 to 10000 ms |
| `SQL_TOOL_TIMEOUT_MS` | `10000` | Cooperative SQL tool budget, from 100 to 30000 ms |
| `OPENAI_API_KEY` | Empty | Server-side secret for real embeddings; not needed by offline tests |
| `EMBEDDING_PROVIDER` | `openai` | Embedding provider, separate from future LLM settings |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Small or text-embedding-3-large |
| `EMBEDDING_DIMENSIONS` | `1536` | At most 1536 for small, 3072 for large |
| `EMBEDDING_INDEX_VERSION` | `v1` | Application vector-space version; changes require reindexing |
| `KNOWLEDGE_INDEX_NAME` | `default` | Server-selected named corpus/index |
| `EMBEDDING_TIMEOUT_SECONDS` | `20` | Per-provider request timeout, from 1 to 30 seconds |

Database sessions use UTC and a one-second lock timeout. The SQL tool applies its
own limits and can accept a shorter absolute monotonic deadline from server code.

## Synthetic dataset and reference date

The dataset version is **synthetic-v1**, with random seed **20261001** and a fixed
reference date of **2026-10-01 00:00:00 UTC**. It contains:

| Table | Rows |
|---|---:|
| analytics.users | 10,000 |
| analytics.orders | 20,000 |
| analytics.events | 80,000 |
| analytics.subscriptions | 3,000 |

All money is EUR and uses NUMERIC(12,2). Timestamps are timezone-aware. Last month
means September 2026; last week means the previous complete Monday-to-Monday week,
September 21 through September 27 inclusive. Both use exclusive end boundaries.
`GET /demo` exposes the configured reference date and synthetic label; it does
not check whether the data has been loaded.

Repeating seed on matching data reports `unchanged`. The full ordered dataset is
checked using SHA-256. Differing data is preserved unless replacement is explicit:

```bash
# Only for replacing this project's synthetic analytics dataset.
docker compose run --rm seed python -m scripts.seed --replace
# Or with local Python:
uv run --locked python -m scripts.seed --replace
```

Replacement is transactional and touches only the four analytics tables. Neither
seed nor role provisioning runs during web server startup.

## Database roles

Use a dedicated local QueryLens PostgreSQL cluster. PostgreSQL login roles are
cluster-wide; `provision-roles` creates/updates the fixed roles and their passwords.
It refuses role memberships and object ownership. It also revokes PUBLIC database
CREATE/TEMPORARY and public schema CREATE. Do not run it on a shared production
cluster without adapting the administration process.

| Role | Purpose and permissions |
|---|---|
| Local owner (`POSTGRES_USER`) | Migrations, provisioning, seed, and current health checks |
| querylens_analytics_ro | SELECT on the four analytics tables; no writes, DDL, temp tables, or knowledge access |
| querylens_knowledge_writer | Read/write on knowledge tables created by the migration owner; no analytics access or schema CREATE |
| querylens_knowledge_ro | SELECT on knowledge tables; no analytics, writes, DDL, or sequences |

The reader has PostgreSQL defaults for read-only transactions, a 5-second statement
timeout, a 1-second lock timeout, and UTC. These defaults can be changed by a
client; integration tests therefore also check permissions after explicitly
switching to a read-write transaction. New analytics relations require explicit
grants. Future knowledge tables/sequences inherit writer grants, and future
knowledge tables inherit reader SELECT, when created by the same migration owner.

Role passwords are not embedded in migrations or sent as plaintext SQL statements;
provisioning uses client-generated SCRAM verifiers. Dedicated passwords are passed
only to the jobs that need them. The `query` job receives only reader credentials;
owner and ingestion credentials are absent from its environment. The API has no
model-generated SQL endpoint yet.

## Validated database tools

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
These are backend tools and a local CLI; LLM dispatch will be added in stage 4.

The policy validates every AST node and lexical relation scope. It accepts one
SELECT, nonrecursive read CTEs, nested/correlated queries, joins, aggregates,
set operations, and a limited set of window/date/string functions. Physical
tables are qualified to `analytics`. Writes (including unused write CTEs), DDL,
COPY, SELECT INTO, locking, extra statements, recursive CTEs, knowledge/catalog
relations, qualified or unapproved functions, and unapproved casts are rejected.
Comments are removed. Input is limited to 16 KiB, 600 AST nodes, and depth 40.
Exact reviewed node/function/type allowlists live in
[sql_validation.py](app/tools/sql_validation.py). SQLGlot is pinned because parser
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
global workflow deadline, retry/tool budgets, and public concurrency limits are
planned in later stages.

## Knowledge ingestion and retrieval

Add `OPENAI_API_KEY` to your local `.env` for real embeddings. Keep the key out of
chat, Git, and client-side code. For an existing stage 2 setup, also add a distinct
`KNOWLEDGE_READONLY_PASSWORD`, upgrade migrations, and reprovision roles:

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked python -m scripts.provision_roles
uv run --locked python -m scripts.ingest --dry-run
uv run --locked python -m scripts.ingest
uv run --locked python -m scripts.search 'How is ARPU calculated?'
```

Docker equivalents:

```bash
docker compose run --build --rm migrate
docker compose run --rm provision-roles
docker compose run --rm ingest python -m scripts.ingest --dry-run
docker compose run --rm ingest
docker compose run --rm search python -m scripts.search 'How is ARPU calculated?'
```

Dry-run reads Markdown and reports chunk count, sources, corpus hash, and input
bytes without DB/API access. No ingestion runs during API startup. `ingest`
receives only writer credentials and the embedding key; `search` receives only
knowledge reader credentials and the key. The SQL `query` job receives neither
the key nor knowledge credentials. The API serves foundation health/demo
endpoints; it does not dispatch LLM tools yet.

Markdown is split by ATX headings and line boundaries, splitting long lines as
needed. Each chunk includes source and heading context and is at most 2000 UTF-8
bytes. Ids/content hashes are deterministic. Metadata includes document SHA-256,
heading, ordinal, and original line range. Headings inside fenced code remain
content. This small chunker is not a complete Markdown renderer. Only repository
Markdown is ingested; no public uploads or external URLs. Bounds: 64 files,
64 KiB/file, 1 MiB/corpus, 512 chunks. Empty corpora/documents and symlinks fail.

Default embeddings use `text-embedding-3-small`, with explicit 1536 dimensions,
as documented in the official
[embedding guide](https://developers.openai.com/api/docs/guides/embeddings).
The [API](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
supports `dimensions` for third-generation models. Provider, model, dimensions,
application index version, and chunker version are stored with the corpus.
Incompatible settings fail before provider calls; changing vector space requires:

```bash
uv run --locked python -m scripts.ingest --reindex
# Docker:
docker compose run --rm ingest python -m scripts.ingest --reindex
```

Reindex replaces only the configured named knowledge index. Provider aliases can
evolve: bump `EMBEDDING_INDEX_VERSION` and rebuild when intentionally adopting a
changed space. This version does not pin an undocumented provider snapshot.

Ingestion reuses unchanged content embeddings, updates document metadata, and
removes stale chunks in one transaction. Repeating an unchanged corpus reports
`unchanged` without API calls. Provider/DB failures roll back the new snapshot.
A global advisory lock serializes explicit ingestion jobs and is held during
embedding requests. Searches see a complete previous snapshot until commit.
The cooperative ingestion deadline is 60 seconds; large or concurrent jobs may
fail rather than extend it.

Search embeds the query and runs exact pgvector cosine search in a read-only,
repeatable-read transaction over the compatible named index. It returns up to
5 sources by default (maximum 8), with source ids, paths, headings, line citations,
hashes, text, and similarity. Query input is capped at 2000 UTF-8 bytes; results
default to 16 KiB, with explicit truncation. Similarity below 0.2 is excluded;
no qualifying source yields `insufficient_context`. The threshold is a heuristic,
not a relevance guarantee; similarity is not a confidence probability. Retrieved
text is untrusted data and cannot change tools/permissions. The SQL validator
continues to exclude all knowledge relations. No answer generation is performed.

The adapter batches at most 16 inputs and disables SDK retries. UTF-8 byte count
conservatively bounds byte-level BPE tokens, avoiding runtime tokenizer downloads.
Each CLI client limits attempted input to 250000 bytes (search: 2000). Paid smoke
verification shares this budget across ingestion and queries and reports actual
provider token usage. The documented
[small-model price](https://developers.openai.com/api/docs/models/text-embedding-3-small)
on 2026-10-07 is $0.02 per million input tokens; this conservative smoke budget is
at most $0.005 at that price. This is a dated estimate, not billing measurement.
Verify current pricing/account access before running. Network timeouts remain
cooperative, as with the SQL tool.

Explicit paid verification checks revenue, ARPU, churn, and repeat ingestion:

```bash
uv run --locked python -m scripts.verify_retrieval --live
# Or:
docker compose run --rm verify-retrieval
```

This uses real embeddings and never substitutes stub vectors. Offline tests mock
provider transport; PostgreSQL tests use labeled stub geometry for vector storage,
ranking, constraints, permissions, and atomicity. Those tests do not establish
semantic retrieval quality.

## Metric documentation and control SQL

Definitions and limitations are documented in:

- [Metrics](knowledge/metrics.md): revenue, active users, ARPU, ARPPU, conversion, churn.
- [Database](knowledge/database.md): columns, constraints, indexes, joins, and roles.
- [Business rules](knowledge/business_rules.md): time anchor and synthetic scenarios.
- [Events](knowledge/events.md): session/checkout meanings and aggregation limits.

Trusted, parameterized queries are in [scripts/sql](scripts/sql). Their `:start`
and `:end` placeholders are bound by SQLAlchemy, not copied directly into psql.
`verify-data` connects as the real analytics reader and compares executed results
with [reference values](scripts/reference_values.json), computed independently by
Python in [reference_metrics.py](scripts/reference_metrics.py). Money is compared
exactly at two decimal places; ratios are rounded to eight decimal places.

September revenue is **336,080.07 EUR**, with **9,501 active users** and **3,396
paying users**. ARPU is **35.37312599 EUR**; ARPPU is **98.96350707 EUR**. The
June empty-period case has 0 revenue and undefined (NULL) ARPU/ARPPU.

The seed deliberately includes a Germany purchase decline and churn differences
between plans. These scenarios support correctness checks; they do not establish
causal explanations. Conversion requires an explicit observation window; the
30-day September cohort is not fully observed and yields an undefined rate.

## Health and migrations

| Endpoint | Behavior |
|---|---|
| `GET /health/live` | HTTP 200 when the API process can serve requests; no database query |
| `GET /health/ready` | HTTP 200 when PostgreSQL is reachable, Alembic is at the bundled heads, and the vector extension is installed; otherwise HTTP 503 |
| `GET /demo` | Static synthetic dataset version, UTC reference date, timezone, and currency; no data-load check |

Readiness errors contain boolean checks rather than credentials or database error
details. Knowledge-index readiness will be added when ingestion is implemented.

The migration service is an explicit job under the `tools` Compose profile;
regular API startup never applies migrations. The first migration enables the
`vector` extension; the second creates analytics tables and a separate knowledge
schema. The third creates knowledge index metadata and vector chunks. Role grants
are provisioned after migration. Foundation readiness checks migrations/pgvector;
it does not check embedding account access or index contents. Retrieval itself
checks compatible index metadata and fails explicitly if missing. To inspect migrations:

```bash
uv run --locked alembic heads
uv run --locked alembic current
```

## Checks

Offline checks need no database service or paid API keys:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -m 'not integration'
```

Offline tests cover settings, credential separation, health behavior, deterministic
seed integrity/reference values, static demo metadata, AST policy, reviewed schema,
and safe tool failures before database access. Readiness success cases
use a stub; verify database behavior after migrations, role provisioning, and seed:

```bash
QUERYLENS_INTEGRATION=1 uv run --locked pytest -m integration
```

Integration tests use the database and role passwords in `.env`. They check real
login permissions, timeout, role isolation, constraints, seed repeatability,
reference SQL, and date-boundary/denominator behavior. Temporary metric fixtures
are rolled back. SQL tool checks exercise control query values, nested CTEs,
row/byte limits, string escaping, transaction identity/settings, real statement
and lock timeouts, caller deadlines, and recovery after errors. A
disposable knowledge probe table is created and removed.
Run them against the dedicated seeded demo database, not an unrelated database.
RAG tests use isolated named indexes and remove them after each test; they preserve
the real default index and make no paid API calls.

Stage 0 was verified on 2026-10-06: 13 offline tests and one PostgreSQL integration
test passed, along with Ruff lint and formatting checks. The Docker quickstart
passed from a fresh source copy with a new volume. Database outage/recovery and
persistence after recreating containers were also verified.

The Python 3.14.8 upgrade was verified on the same date: all 14 tests and Ruff
checks passed, the lockfile was checked, and the Docker API and migration job ran
successfully on 3.14.8. Both health endpoints returned HTTP 200. Dependency
versions remained unchanged.

Stage 1 was verified on 2026-10-07: 17 offline tests and 26 PostgreSQL integration
tests passed (43 total), as did Ruff lint/format, lockfile checks, and Alembic's
metadata check. The Docker quickstart passed from a fresh source copy with a new
volume, including dedicated-role provisioning, seed, control SQL verification,
and HTTP 200 responses from both health endpoints and `/demo`. All 43 tests also
passed against that fresh database. Repeated seed reported `unchanged`.
On a separate disposable database, a differing dataset was preserved by default,
explicit `--replace` restored the reference fingerprint, and a downgrade/upgrade
round-trip followed by provisioning/seed/verification succeeded. Temporary
verification containers and volumes were removed.

Stage 2 was verified on 2026-10-07: 114 offline and 55 PostgreSQL integration
tests passed (169 total), including the complete SQL tool path. Ruff lint/format,
lockfile validation, and Alembic's metadata check passed. Existing dependency
versions were preserved; only pinned SQLGlot was added. The Docker quickstart
passed again from a fresh source copy and new volume with new temporary secrets;
all 169 tests passed against that database. Docker CLI checks verified CTE
execution, rejected writes, row truncation, and reader credential isolation;
a real statement timeout was also verified through the Docker CLI. Repeated seed
reported `unchanged`, reference values matched, and live/ready/demo returned
HTTP 200. Temporary containers, volumes, source copies, and secrets were removed.

Stage 3 implementation checks on 2026-10-07: 142 offline and 66 PostgreSQL
integration tests passed (208 total), including SDK transport contracts and
real vector/role/atomicity behavior with labeled stub embeddings. Ruff,
lockfile validation, and Alembic metadata checks passed. The fresh Docker setup
with a new volume and temporary secrets passed migrations, three-role
provisioning, seed/reference verification, ingestion dry-run (25 chunks,
15942 input bytes), and HTTP 200 live/ready/demo checks. All 208 tests also passed
against that fresh database. A Docker probe verified stub ingestion/search and
repeat ingestion without additional embedding calls. Job credential isolation,
non-root execution, and exclusion of secrets/local plan were checked. Temporary
containers, volumes, source, secrets, and probe indexes were removed.
Live OpenAI retrieval has not run: an API key is still required. Stage 3
acceptance remains pending that explicit paid smoke check.

## Scope and next steps

This is a local foundation, with no deployed demo yet. The local database owner
currently serves health/migration paths; validated SQL uses a separate reader.
There is no public SQL endpoint or LLM workflow. Knowledge ingestion and exact
retrieval are implemented; live verification is pending an embedding API key.

Next after live stage 3 acceptance: OpenAI Responses API with real tool calls.
