# QueryLens

QueryLens is being built to answer business questions using documentation
retrieval, LLM tool calling, and read-only SQL over synthetic PostgreSQL data.

**Current status: stage 0 — local backend and database foundation.** The health
API, configuration, migrations, and Docker environment are implemented. Analytics
tables, synthetic data, retrieval, LLM integration, and the demo UI come next.
No LLM API key is required for this stage.

## Stack

- Python 3.12 and uv with dependencies pinned in `uv.lock`.
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

Set `POSTGRES_PASSWORD` in `.env` to a local password. The example value is a
placeholder. `.env` is excluded from Git and the Docker build context.

Start the database, apply migrations, then start the API:

```bash
docker compose up -d --wait db
docker compose run --build --rm migrate
docker compose up --build -d --wait api
```

Open [interactive API documentation](http://127.0.0.1:8000/docs) or check health:

```bash
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
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

Install [uv](https://docs.astral.sh/uv/getting-started/installation/). uv selects
Python 3.12 using `.python-version` and downloads it when necessary. Follow the
environment setup above, then run:

```bash
uv sync --locked
docker compose up -d --wait db
uv run --locked alembic upgrade head
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

Database sessions use UTC and a one-second lock timeout. These limits support
health checks; the future SQL execution tool will also enforce its own permissions,
result limits, and request deadline.

## Health and migrations

| Endpoint | Behavior |
|---|---|
| `GET /health/live` | HTTP 200 when the API process can serve requests; no database query |
| `GET /health/ready` | HTTP 200 when PostgreSQL is reachable, Alembic is at the bundled heads, and the vector extension is installed; otherwise HTTP 503 |

Readiness errors contain boolean checks rather than credentials or database error
details. Knowledge-index readiness will be added when ingestion is implemented.

The migration service is an explicit job under the `tools` Compose profile;
regular API startup never applies migrations. The first migration enables the
`vector` extension and records its Alembic revision. To inspect migrations:

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

Unit tests cover settings, secret handling, health behavior, and sanitized database
failures. Readiness success cases in unit tests use a stub; verify real database
behavior separately after starting PostgreSQL and applying migrations:

```bash
QUERYLENS_INTEGRATION=1 uv run --locked pytest -m integration
```

The integration test checks readiness, a real vector-distance operation, and UTC
sessions against the migrated database configured in `.env`. It does not alter
business data.

Stage 0 was verified on 2026-10-06: 13 offline tests and one PostgreSQL integration
test passed, along with Ruff lint and formatting checks. The Docker quickstart
passed from a fresh source copy with a new volume. Database outage/recovery and
persistence after recreating containers were also verified.

## Scope and next steps

This is a local foundation, with no deployed demo yet. The local database owner
currently serves the health and migration paths. Stage 1 will add separate roles
and grants for analytics and knowledge storage; the future model-generated SQL
tool will use its own read-only credentials.

The complete architecture, acceptance criteria, and current handoff are in
[`QUERYLENS_PLAN.md`](QUERYLENS_PLAN.md). Next: analytics schema, roles, reproducible
synthetic seed data, and metric documentation.
