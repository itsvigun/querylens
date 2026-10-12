# Configuration

[Documentation index](README.md)

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
| `OPENAI_API_KEY` | Empty | Server-side secret for embeddings and Responses; not needed by offline tests |
| `EMBEDDING_PROVIDER` | `openai` | Embedding provider, separate from LLM settings |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Small or text-embedding-3-large |
| `EMBEDDING_DIMENSIONS` | `1536` | At most 1536 for small, 3072 for large |
| `EMBEDDING_INDEX_VERSION` | `v1` | Application vector-space version; changes require reindexing |
| `KNOWLEDGE_INDEX_NAME` | `default` | Server-selected named corpus/index |
| `EMBEDDING_TIMEOUT_SECONDS` | `20` | Per-provider request timeout, from 1 to 30 seconds |
| `LLM_MODEL` | `gpt-5.4-mini` | Verified Responses/tool-calling contract; separate from embeddings |
| `LLM_TIMEOUT_SECONDS` | `20` | Per-Responses-request timeout, at most 30 seconds |
| `REQUEST_TIMEOUT_SECONDS` | `60` | Cooperative deadline for one question, at most 120 seconds |
| `LLM_MAX_CALLS` | `6` | Maximum Responses requests per question |
| `LLM_MAX_TOOL_CALLS` | `8` | Maximum dispatched tools per question |
| `LLM_MAX_SQL_CALLS` | `3` | Total SQL attempts, including rejected/failed queries |
| `LLM_MAX_SQL_REPAIRS` | `2` | Additional SQL attempts after a failed query, from 0 to 2 |
| `LLM_MAX_INPUT_BYTES` | `128000` | Cumulative serialized request bytes, plus protocol allowances |
| `LLM_MAX_OUTPUT_TOKENS` | `4000` | Total output-token allowance; at most 1000 per request |

Database sessions use UTC and a one-second lock timeout. The SQL tool applies its
own limits and can accept a shorter absolute monotonic deadline from server code.

The checked-in [`.env.example`](../.env.example) is the starting template;
[`app/config.py`](../app/config.py) defines validation and bounds, and
[`docker-compose.yml`](../docker-compose.yml) controls job environments.
Embedding and LLM settings are independent. Changing the LLM does not change the
vector space; changing embedding/index settings requires explicit reindexing.
Keep all passwords and provider keys server-side and outside Git, logs and images.

## Public demo settings

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_DEMO_ENABLED` | `false` locally | Enable shared PostgreSQL admission; required on Railway |
| `DEMO_CONTROL_PASSWORD` | Required in public mode | Dedicated `querylens_demo_control` secret; no owner fallback |
| `PUBLIC_CHAT_MONTHLY_BUDGET_USD` | `0` | Known-cost UTC-month threshold, up to $100, at most six decimal places; zero disables paid public chat |
| `PUBLIC_CHAT_REQUESTS_PER_MINUTE` | `6` | Global fixed UTC-minute admitted-request cap, 1–60 |
| `PUBLIC_CHAT_MAX_CONCURRENT` | `1` | Shared durable active-lease cap, 1–4; local process guard remains one |
| `PORT` | `8000` | Docker/PaaS HTTP port, 1–65535, read by `scripts.serve` |

The optional Railway-provided `RAILWAY_ENVIRONMENT_ID` makes disabled public
controls a startup error. Configure the matching policy explicitly using owner
credentials; workers cannot change policy. Money is never reserved: complete usage
is estimated after completion. Thresholds can be crossed by the final admitted
request(s); unknown usage is explicitly recorded and excluded from known-cost sums. See [deployment](deployment.md) for
pricing assumptions, credential separation, recovery and actual acceptance limits.

## Invitation access settings

| Variable | Default | Purpose |
|---|---|---|
| `TOKEN_ACCESS_REQUIRED` | Unset; false locally, required on Railway | Enable HTTP invitation authentication; false is rejected on Railway |
| `ACCESS_PUBLIC_ORIGIN` | Unset | Exact browser origin, with scheme and optional port, no trailing slash/path; falls back to `https://RAILWAY_PUBLIC_DOMAIN` |
| `ACCESS_COOKIE_SECURE` | `true` | Secure host-only production cookie; false is allowed only for local loopback development |
| `ACCESS_SESSION_TTL_SECONDS` | `28800` | Session lifetime, 300–86400 seconds, capped by token expiry |

Invitation mode also requires `PUBLIC_DEMO_ENABLED=true`, the configured global
policy and the dedicated control role. It fails closed when authentication storage
is unavailable. Docker Compose forwards these settings and defaults to local HTTP
with insecure development cookies; its origin defaults to `http://127.0.0.1:8000`.
Match an overridden `API_PORT` with an explicit origin. For Railway/custom domains,
use the final HTTPS origin and secure cookies; do not copy Compose's local false
overrides into hosted variables. Full owner CLI and quota bounds: [access.md](access.md).
