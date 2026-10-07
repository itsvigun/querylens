# QueryLens

QueryLens is being built to answer business questions using documentation
retrieval, LLM tool calling, and read-only SQL over synthetic PostgreSQL data.

**Current status: stage 1 — synthetic analytics data and metric documentation.**
The API foundation, analytics schema, dedicated database roles, reproducible seed,
and control SQL are implemented. Retrieval, LLM integration, and a demo UI come
next. No LLM API key is required for this stage.

## Stack

- Python 3.14.8 and uv with dependencies pinned in `uv.lock`.
- FastAPI and Uvicorn.
- SQLAlchemy 2.0 and psycopg2 for PostgreSQL connections.
- Alembic for explicit database migrations.
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

Set `POSTGRES_PASSWORD`, `ANALYTICS_READONLY_PASSWORD`, and
`KNOWLEDGE_WRITER_PASSWORD` in `.env` to distinct local passwords. Dedicated-role
passwords must have at least 16 characters. Example values are placeholders.
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
| `ANALYTICS_READONLY_PASSWORD` | Required for provisioning/verification | Dedicated reader password; never falls back to owner credentials |
| `KNOWLEDGE_WRITER_PASSWORD` | Required for provisioning | Dedicated ingestion writer password |

Database sessions use UTC and a one-second lock timeout. These limits support
health checks; the future SQL execution tool will also enforce its own permissions,
result limits, and request deadline.

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

The reader has PostgreSQL defaults for read-only transactions, a 5-second statement
timeout, a 1-second lock timeout, and UTC. These defaults can be changed by a
client; integration tests therefore also check permissions after explicitly
switching to a read-write transaction. New analytics relations require explicit
grants. Future knowledge tables/sequences inherit grants for the knowledge writer
when created by the same migration owner.

Role passwords are not embedded in migrations or sent as plaintext SQL statements;
provisioning uses client-generated SCRAM verifiers. Dedicated passwords are passed
only to the jobs that need them. The API has no model-generated SQL endpoint yet;
stage 2 will enforce validation and execution limits with dedicated reader settings.

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
schema. Role grants are provisioned after migration. To inspect migrations:

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
seed integrity/reference values, and static demo metadata. Readiness success cases
use a stub; verify database behavior after migrations, role provisioning, and seed:

```bash
QUERYLENS_INTEGRATION=1 uv run --locked pytest -m integration
```

Integration tests use the database and role passwords in `.env`. They check real
login permissions, timeout, role isolation, constraints, seed repeatability,
reference SQL, and date-boundary/denominator behavior. Temporary metric fixtures
are rolled back; a disposable knowledge probe table is created and removed.
Run them against the dedicated seeded demo database, not an unrelated database.

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

## Scope and next steps

This is a local foundation, with no deployed demo yet. The local database owner
currently serves the health and migration paths. Role permissions are implemented,
but arbitrary generated SQL is not yet a supported interface: AST validation,
function/relation allowlists, server-controlled read-only transactions, row/byte
limits, and structured tool results come in stage 2. Knowledge documents are
Markdown only; ingestion, embeddings, retrieval, and paid API calls are not run.

Next: schema metadata and validated, bounded read-only database tools.
