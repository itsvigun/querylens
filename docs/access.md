# Invitation access

[Documentation index](README.md)

Give each CV recipient a named invitation code, without registration. The owner
creates, updates and revokes codes through a CLI. There is no administrative HTTP
endpoint. The company label identifies the intended recipient; someone can forward
the code, so it does not establish the real identity of the visitor.

Invitation login is deployed and the author confirmed access on Railway. The
post-request accounting change requires migration `0006_post_request_usage`,
updated grants and policy configuration before deploying the new API; see
[deployment](deployment.md#post-request-accounting-upgrade).

## Access flow

In protected mode, `/`, `/assets/*`, `/health/live` and `/health/ready` remain
public. `/demo`, `/docs`, `/openapi.json`, `/redoc`, `/api/chat` and other routes
require a valid invitation/session. Login and logout are public routes with
same-origin checks. Opening the entry page makes no provider call.

The browser exchanges a code at `POST /api/access/login` for a database-backed
session. Production uses a host-only `__Host-querylens_session` cookie with
`Secure`, `HttpOnly`, `SameSite=Strict`, path `/` and no Domain. The lifetime is
8 hours by default and never exceeds the invitation expiry. Up to eight active
sessions per invitation are allowed. Session credentials are hashed in PostgreSQL;
no signing secret needs rotation across workers. Reloading/restarting the API
preserves an unexpired session. Sign out deletes it. Expiry or revocation blocks
all associated sessions at the next authentication/admission check; a request
already admitted can finish.

Cookie-authenticated POST requests require the configured exact Origin,
`X-QueryLens-Client: browser`, and an `X-CSRF-Token` obtained from login/status.
The nonce stays in JavaScript memory. No code is placed in a URL or localStorage.
API clients use `Authorization: Bearer <invitation code>` instead. In Swagger,
click **Authorize** and enter the code to submit requests. CLI tools such as
`scripts.ask` are owner/developer jobs and do not use HTTP invitation quotas.

## Quotas and accounting

Each invitation defaults to **10 lifetime questions**, a **USD 1 measured-usage
threshold**, 2 questions/minute and 30-day expiry. Request counts, authentication,
rate limits and one active question per invitation are checked atomically with
the global rate/concurrency controls before any provider call. An admitted question
uses one question even if its answer fails; login, metadata reads and pre-admission
denials use none. Updates preserve counts and existing credentials.

There are **no monetary reservations**. Completion uses full LLM and embedding
usage to estimate standard uncached cost, rounded up to integer micro-USD. The same
transaction records the cost against the invitation and the admission's UTC month,
and releases its concurrency lease. Duplicate completion cannot count twice.
Known consumption is recorded even if the answer is unsuccessful. Estimates are
not OpenAI invoices: cached discounts, taxes and account balance are not reconciled.

USD limits are **soft thresholds**: a new question is denied once known accumulated
cost reaches the threshold. The final question can cross it. One active question
per invitation limits parallel overshoot; up to the configured global concurrency
can cross the shared threshold. Existing provider/token/deadline limits still bound
individual requests. A zero USD threshold disables admission.

Partial/missing usage is recorded as `unknown`, with a NULL request cost and an
`unknown_requests` counter; no maximum or zero cost is invented. These requests
still consume the question allowance. A crashed request keeps its concurrency
lease until explicit owner recovery. Unknown costs are excluded from the known-cost
sum, so it is not a complete spending guarantee. Owner/developer CLI, ingestion and
evaluation remain outside the HTTP quotas and need separate allowances.

The shared allocation remains USD 1 per UTC calendar month; this change does not
raise it to USD 100. The UI shows questions left independently from personal/shared
budget availability and disables submission when either money threshold is reached.
Ten questions no longer need a USD 1.20 reservation cap. Existing limits stay as
issued; use the owner update command to set an existing code to 10 questions/USD 1.

Migration `0006` archives old monthly reservations in `legacy_reserved_micro_usd`.
Existing token/request `reserved_micro_usd` fields are historical only. New known-cost
counters start at zero at migration; old costs cannot be reliably reconstructed
from reserves and are excluded from new thresholds. Tokens, sessions, request counts,
rate counters and audit rows are preserved. A `legacy` record has unknown measured
cost; it is not a free request. No reserve reconciliation job is needed.

## Owner commands

Use the database owner credentials from [setup](setup.md), never the API's runtime
role. Run the explicit migration, provisioning and policy configuration first. Do not reset the ledger
or repeat seed/ingestion to enable invitations.

```bash
uv run --locked alembic upgrade head
uv run --locked python -m scripts.provision_roles
# With PUBLIC_DEMO_ENABLED=true and matching API settings; all workers stopped:
uv run --locked python -m scripts.demo_policy --configure
uv run --locked python -m scripts.access_tokens create \
  --name "Acme — Backend interview" \
  --max-requests 10 --budget-usd 1 --requests-per-minute 2 \
  --expires-in-days 30 --output .access-tokens/acme.txt
uv run --locked python -m scripts.access_tokens list
```

Creation prints metadata, including `token_id` and the secret file path. The full
code is written only into a new file with mode `0600`; an existing file is never
overwritten. `.access-tokens/` is ignored by Git and Docker. Read/copy that private
file yourself and send the code with the hosted UI URL to the intended recipient.
Do not put it in job logs, screenshots or a tracked CV source. A lost code cannot
be recovered from PostgreSQL: revoke it and issue another.

Use the 32-character `token_id` from the metadata, not the full secret:

```bash
uv run --locked python -m scripts.access_tokens usage TOKEN_ID --limit 50
uv run --locked python -m scripts.access_tokens update TOKEN_ID \
  --max-requests 10 --budget-usd 1 --expires-in-days 30
uv run --locked python -m scripts.access_tokens revoke TOKEN_ID
```

Updates preserve counters; limits are new lifetime totals. Extending expiry counts
from the update time. Revoked invitations cannot be reactivated. `list` returns
at most 1000 invitations; `usage` queries an individual ID and returns the latest
50 requests by default, configurable to 1–1000.

For the hosted database, use the private SSH tunnel in [deployment](deployment.md#inspect-the-hosted-database).
Run the owner CLI on your laptop with `POSTGRES_HOST=127.0.0.1`,
`POSTGRES_PORT=15432`, and the hosted owner/database settings entered privately in
a separate ignored environment file or shell environment. Supply all four role
passwords only when provisioning. Do not copy the local `.env` passwords over
hosted roles. Keep owner credentials out of the API service. Creating the private
file on the laptop avoids printing a credential into a Railway job log.

## Local protected mode

Local development is unprotected unless enabled. The author's active workspace
was enabled on 2026-10-12; a fresh clone must still configure it. To exercise the complete gate,
set these in `.env` after migrating/provisioning:

```dotenv
PUBLIC_DEMO_ENABLED=true
PUBLIC_CHAT_MONTHLY_BUDGET_USD=1
TOKEN_ACCESS_REQUIRED=true
ACCESS_PUBLIC_ORIGIN=http://127.0.0.1:8000
ACCESS_COOKIE_SECURE=false
```

Configure the matching global policy explicitly, then start the API:

```bash
uv run --locked python -m scripts.demo_policy --configure
docker compose up --build -d --wait api
```

For host development, use the Uvicorn command in [setup](setup.md). Match the
origin to the browser URL/port; `localhost` and `127.0.0.1` are distinct origins.
Insecure cookies are accepted only for local loopback HTTP. Railway always requires
invitation access, shared admission and secure HTTPS cookies; disabling them
causes startup failure. After rollout, readiness includes the access schema and
runtime permission check; it still does not establish AI/index readiness.

## Audit and security boundaries

`usage` joins the owner-assigned name with counters and sanitized request records:
request ID, times, estimated micro-USD/usage state, legacy reserves, pricing version,
HTTP status, result/error category, model IDs, actual token counts, bounded tool counters and duration.
`first_used_at`/`last_used_at` mean admitted questions, not logins. Authenticated
invalid/denied chat requests have `not_admitted` audit rows without a measured cost. Anonymous
or invalid-code attempts have no verified token identity and appear only in fixed
category logs. Console logs use token IDs, without names or secrets.

Pending records are inserted with admission and completed after the response.
If completion cannot be persisted, `audit_recorded=false` appears in logs and the
pending record remains unknown. Stop all workers before explicit stale-lease
recovery; it marks pending usage `request_interrupted`/`unknown` without inventing
a monetary charge. Reports distinguish recorded, unknown, pending and legacy usage.
No question, SQL, result content, credential, header, IP or user agent is stored
in this audit. See [observability](observability.md).

Credentials contain 256 random secret bits; only SHA-256 digests are stored, and
comparison is constant-time. Runtime control credentials can read token metadata,
update usage and manage sessions/audit, but cannot issue/revoke tokens or change
limits/policy. Analytics and knowledge readers cannot access these tables. The
code rejects invitation/session credential patterns inside a question before
admission, preventing accidental forwarding to the model. Provider/database
secrets remain server-side.

No registration, public admin UI, token URL links, automatic retries or external
tracking are added. This small deployment relies on its hosting edge for broader
network abuse protection; invitation rates bound admitted AI questions rather
than every HTTP connection. PostgreSQL audit/session data grows with use; retention
and cleanup beyond expired sessions are owner operations, not automatic history
loss. Verification uses stubs and disposable PostgreSQL, with no paid calls.


## Creating hosted invitations from the laptop

Use this after applying migration `0006`, re-provisioning existing hosted role
passwords, configuring the new policy and deploying the protected API according to the rollout guide. Open
the private tunnel in one terminal (leave it running):

```bash
railway ssh config --service db --environment production --alias querylens-db
ssh -N -L 127.0.0.1:15432:127.0.0.1:5432 querylens-db
```

Create an ignored `.env.production` on the laptop, with file mode `0600`. Enter
hosted values yourself; the password is `db.POSTGRES_PASSWORD`, and the username
and database come from `db.POSTGRES_USER` / `db.POSTGRES_DB`. This file only needs
owner connection settings for invitation administration:

```dotenv
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=15432
POSTGRES_USER=your_hosted_owner
POSTGRES_DB=your_hosted_database
POSTGRES_PASSWORD=your_hosted_owner_password
```

In another terminal, from the repository root:

```bash
uv run --locked --env-file .env.production python -m scripts.access_tokens create \
  --name "Acme — Backend interview" \
  --max-requests 10 --budget-usd 1 --expires-in-days 30 \
  --output .access-tokens/acme-production.txt
uv run --locked --env-file .env.production python -m scripts.access_tokens list
uv run --locked --env-file .env.production python -m scripts.access_tokens usage TOKEN_ID
uv run --locked --env-file .env.production python -m scripts.access_tokens revoke TOKEN_ID
```

`uv --env-file` puts these hosted settings in the process environment, which takes
precedence over the local development `.env`. The private invitation file contains
the full code; stdout contains metadata only. Give the recipient the code and the
hosted homepage URL separately. Keep the SSH tunnel/environment file private and
close the tunnel when finished. All codes share the currently approved USD 1/month
known-cost threshold. These commands do not raise it or synchronize OpenAI balance.
