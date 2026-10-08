# QueryLens

Ask business questions over synthetic PostgreSQL data. QueryLens retrieves metric
definitions, uses OpenAI tool calls to execute validated read-only SQL, and returns
answers with queries, results and sources.

**Status:** stage 7 implementation — web UI, bounded LangGraph, synthetic evaluation,
structured logs and CI.
The demo uses EUR and a fixed reference date of **2026-10-01 UTC**.
[Verification evidence](docs/verification.md#stage-7).

**Stack:** Python 3.14, FastAPI, PostgreSQL/pgvector, SQLAlchemy, Alembic,
OpenAI Responses, LangGraph, uv and Docker Compose.

## Quickstart

Requires Git and a running Docker installation with Compose v2 or later.

```bash
git clone git@github.com:itsvigun/querylens.git
cd querylens
cp .env.example .env
```

Set distinct local passwords of at least 16 characters for `POSTGRES_PASSWORD`,
`ANALYTICS_READONLY_PASSWORD`, `KNOWLEDGE_WRITER_PASSWORD` and
`KNOWLEDGE_READONLY_PASSWORD` in `.env`. Add `OPENAI_API_KEY` to enable real chat;
startup, health and offline tests need no key.

```bash
docker compose up -d --wait db
docker compose run --build --rm migrate
docker compose run --rm provision-roles
docker compose run --rm seed
docker compose run --rm verify-data
docker compose up --build -d --wait api
```

For chat, populate the knowledge index with real embeddings (paid API call):

```bash
docker compose run --rm ingest
```

Open [QueryLens](http://127.0.0.1:8000/) and ask, for example,
“What was revenue last month, in EUR?” [API documentation](http://127.0.0.1:8000/docs)
is also available.
Services bind to loopback. Health endpoints are `/health/live` and `/health/ready`;
`/demo` exposes the synthetic dataset metadata. Stop with `docker compose down`;
the database volume is preserved.

## Documentation

[Documentation index](docs/README.md) — start here for development context.

- [Setup and host development](docs/setup.md) · [Configuration](docs/configuration.md)
- [Architecture](docs/architecture.md) · [Data and metrics](docs/data.md)
- [SQL tool](docs/sql-tool.md) · [Retrieval](docs/retrieval.md) · [Chat and LangGraph](docs/chat.md)
- [Web UI](docs/ui.md) · [Evaluation](docs/evaluation.md) · [Observability](docs/observability.md)
- [Testing](docs/testing.md) · [CI](docs/ci.md) · [Verification record](docs/verification.md)

Working rules: [AGENTS.md](AGENTS.md). Business definitions: [knowledge/](knowledge).
