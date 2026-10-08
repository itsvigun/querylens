# Setup and operations

[Documentation index](README.md)

Run all commands from the repository root.

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

Open the [web UI](http://127.0.0.1:8000/) or
[interactive API documentation](http://127.0.0.1:8000/docs), or check health:

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

## Health and migrations

| Endpoint | Behavior |
|---|---|
| `GET /health/live` | HTTP 200 when the API process can serve requests; no database query |
| `GET /health/ready` | HTTP 200 when PostgreSQL is reachable, Alembic is at the bundled heads, and the vector extension is installed; otherwise HTTP 503 |
| `GET /demo` | Static synthetic dataset version, UTC reference date, timezone, and currency; no data-load check |

Readiness errors contain boolean checks rather than credentials or database error
details. This is foundation readiness; it does not establish end-to-end AI readiness.

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

## Enable chat

The foundation setup needs no API key. For real ingestion, retrieval and chat,
set `OPENAI_API_KEY` in the local `.env`, then follow the
[retrieval guide](retrieval.md) to populate the default index. If the API was
already running when the key or other environment settings changed, apply the
new environment with:

```bash
docker compose up -d --wait api
```

Open `/` to ask through the [web UI](ui.md), `/docs` to call `POST /api/chat`,
or use the [chat CLI](chat.md).
Health checks do not call OpenAI. Migrations, role provisioning, seed and
knowledge ingestion are explicit jobs, not startup tasks.
