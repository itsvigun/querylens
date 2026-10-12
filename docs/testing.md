# Testing and acceptance

[Documentation index](README.md)

Run all commands from the repository root.

Offline checks need no database service or paid API keys:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -m 'not integration and not browser'
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

## Lockfile and schema drift

```bash
uv lock --check
uv run --locked alembic check
```

`alembic check` needs the migrated demo database. The backend suite uses:

```bash
QUERYLENS_INTEGRATION=1 uv run --locked pytest -m 'not browser' -q
```

## Targeted workflow checks

```bash
uv run --locked pytest tests/test_workflow.py -q
QUERYLENS_INTEGRATION=1 uv run --locked pytest tests/test_llm_integration.py -q
```

## Browser checks

Install the optional browser group and its pinned Chromium binary once:

```bash
uv sync --locked --group browser
uv run --locked --group browser playwright install chromium
QUERYLENS_BROWSER=1 uv run --locked --group browser pytest -m browser -q
```

These tests start a temporary local FastAPI server. Every chat call uses a labeled
offline answer; they require no database or API key and make no paid calls.
They cover desktop/mobile layout, literal rendering of untrusted content, exact
numeric strings, NULL/empty/truncated results, clarification, failures, busy and
timeout states, and manual retry. Browser checks skip unless explicitly enabled.
Set `QUERYLENS_SCREENSHOT_DIR` to a temporary directory to save labeled fixture
screenshots from the desktop/mobile answer checks.

Run all three groups against the prepared demo database:

```bash
QUERYLENS_INTEGRATION=1 QUERYLENS_BROWSER=1 uv run --locked --group browser pytest -q
```

The browser dependency group is excluded from the production Docker image.

## Evaluation and CI

The twenty-case [evaluation](evaluation.md) uses real PostgreSQL with scripted
calls/stub vectors and requires no API key:

```bash
mkdir -p artifacts
uv run --locked python -m scripts.evaluate --offline --output artifacts/evaluation.json
```

Grader tests reject incorrect metrics, broken provenance, missing source/citation
coverage and malformed CLI/live-budget selection. The integration evaluation test
checks all twenty scenarios and that disposable indexes are removed while existing
indexes remain unchanged. JSON logging tests inject secrets into submitted data,
results and exceptions, and cover success, validation, busy, failures and concurrency.
[CI](ci.md) runs offline, PostgreSQL and browser groups independently with no key.
Live evaluation is a separate paid command requiring explicit total byte/token budgets;
the full sixteen-case live suite has not been run.

## Live provider acceptance

Live checks are paid and are separate from offline tests. Agree on a budget and
configure a server-side key before running them. Retrieval acceptance includes
real ingestion, repeat ingestion and three metric searches; tool-calling acceptance
requires a compatible index and checks the live revenue result through LangGraph.

```bash
uv run --locked python -m scripts.verify_retrieval --live
uv run --locked python -m scripts.verify_tool_calling --live
```

See [retrieval](retrieval.md) and [chat](chat.md) for exact byte/token limits,
dated cost estimates and Docker equivalents. See [verification.md](verification.md)
for actual past checks, attribution and usage. Do not treat historical test counts
or a single live question as general accuracy or performance evidence.

When verifying a fresh setup, follow [setup.md](setup.md) in an isolated source
copy with a new dedicated database and temporary secrets. Remove only that
verification environment when finished; preserve the main dataset and default index.

## Public deployment preparation

After migration `0004_demo_controls` and provisioning the demo role:

```bash
uv run --locked pytest tests/test_demo_gate.py -q
QUERYLENS_INTEGRATION=1 uv run --locked pytest tests/test_demo_gate_integration.py -q
```

The integration fixture requires an **unused operations ledger** on the dedicated
local test DB and refuses a populated ledger before deleting anything. It never
clears a live/public ledger. Tests exercise atomic race admission, durable charges
and crash leases, fixed-minute limits, monthly rollover, policy changes, denied
permissions and zero-budget public HTTP without paid calls. Browser fixtures
exercise specific public limit messages with no automatic retries. Follow the
separate [deployment acceptance](deployment.md#backups-and-deployment-acceptance)
on a real URL before marking hosting complete.

## Invitation access checks

```bash
uv run --locked pytest tests/test_access.py -q
QUERYLENS_INTEGRATION=1 uv run --locked pytest tests/test_access_integration.py -q
QUERYLENS_BROWSER=1 uv run --locked --group browser pytest tests/test_ui_browser.py -q
```

Use a fresh migrated/provisioned/seeded disposable database: access integration
fixtures require all operations tables to be empty and remove only their own
records. Never target the hosted ledger. They check hashed storage, private files,
wrong/expired/revoked credentials, sessions/logout, concurrent quota admission,
per-token/global rollback, durable audit, interrupted-request recovery, role ACLs
and real HTTP readiness/accounting without a key/provider. Browser fixtures cover
entry/cookie/reload/logout on desktop/mobile and revocation without retries.
They establish access/control behavior, not semantic AI quality. Existing CI's
three test groups include these files automatically without paid keys.
