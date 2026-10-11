# Verification record

[Documentation index](README.md)

This is dated evidence, not a list of checks automatically run on every change.
Start with [stage 6](#stage-6) for the latest implementation evidence.
For current commands, use [testing.md](testing.md).
Offline provider transports and stub vectors are labeled separately from live API runs.

## Stage 0

Stage 0 was verified on 2026-10-06: 13 offline tests and one PostgreSQL integration
test passed, along with Ruff lint and formatting checks. The Docker quickstart
passed from a fresh source copy with a new volume. Database outage/recovery and
persistence after recreating containers were also verified.

## Python 3.14.8 upgrade

The Python 3.14.8 upgrade was verified on the same date: all 14 tests and Ruff
checks passed, the lockfile was checked, and the Docker API and migration job ran
successfully on 3.14.8. Both health endpoints returned HTTP 200. Dependency
versions remained unchanged.

## Stage 1

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

## Stage 2

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

## Stage 3

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
Stage 3 live acceptance subsequently passed on 2026-10-08, as recorded below.

## Stage 4

Stage 4 implementation checks on 2026-10-07: 177 offline and 70 PostgreSQL
integration tests passed (247 total). New checks cover actual SDK Responses JSON,
reasoning/output replay, strict schemas, sanitized API failures/refusals/timeouts,
arguments/context gates, cell/source provenance, undefined and empty results,
concurrency, malformed Unicode and bounded call/context/output budgets. Four
PostgreSQL end-to-end scenarios use offline Responses transport and labeled stub
embeddings: revenue, column repair, rejected writes and excluded knowledge access.
Ruff lint/format, lockfile validation and Alembic metadata checks passed.
A fresh Docker source copy/new volume passed the README foundation setup, HTTP
live/ready/demo/OpenAPI checks, safe missing-key chat failure, reader-only job
credential/image checks, and the four new PostgreSQL scenarios. Temporary
containers/volumes/source/secrets were removed. The main API was rebuilt and left
healthy with `/api/chat` available. No new dependency versions were introduced.
Stage 4 live acceptance subsequently passed on 2026-10-08, as recorded below.

## Stages 3 and 4 live acceptance

Live checks on 2026-10-08:

- The author ran `scripts.verify_tool_calling --live` and supplied its successful
  output (`verified=true`). GPT-5.4-mini made three Responses requests and called
  schema, documentation and SQL tools. Executed SQL used completed orders, UTC
  September boundaries and NUMERIC money; its result and the referenced final
  fact were both `336080.07` EUR, with the revenue definition citation.
  Usage was 6581 input and 317 output tokens, plus 12 small-model embedding
  tokens. The single observed run took 7107 ms; this is not a latency benchmark.
- `scripts.verify_retrieval --live` was then run in the workspace and returned
  `status=verified`. Both ingestion passes were unchanged, reused all 25 chunks
  and generated no new document embeddings. Revenue, ARPU and subscription churn
  matched their definitions in `knowledge/metrics.md`. The three search requests
  used 41 embedding tokens (208 input bytes).
- A separate database read confirmed the default OpenAI index contains 25
  chunks, all with nonzero vectors and exactly 1536 dimensions, model
  `text-embedding-3-small`, application index version `v1`.

At the dated model prices linked in [chat.md](chat.md) and [retrieval.md](retrieval.md),
known Responses and query-embedding usage estimates
to $0.00636331 before any cached-input discount. This excludes the initial
document ingestion, whose live usage was not supplied, and is not an invoice.
These live checks establish the specified local scenarios, not general answer
accuracy or deployment performance. Stage 4 Responses evidence is the author's
supplied output; the separate stage 5 regression run is recorded below.

## Stage 5

Stage 5 checks on 2026-10-08: 203 offline and 71 PostgreSQL integration tests
passed (274 total). New checks exercise the compiled graph's successful answer,
clarification, unsupported question, missing context, SQL repair and exhausted
repair/total-attempt/tool/model budgets. They also check duplicate call IDs,
deadline expiry before dispatch and after SQL, sanitized unexpected failures,
the graph step guard and suppression of environment-enabled LangSmith tracing.
Five PostgreSQL end-to-end scenarios use offline Responses transport and labeled
stub embeddings, including three real column errors followed by bounded failure
and successful database recovery. Ruff lint/format, lockfile validation and
Alembic metadata checks passed. Adding LangGraph and its dependencies introduced
25 packages without changing any existing dependency versions.

A fresh Docker source copy with a new volume and temporary secrets passed the
README setup, seed/control verification, live/ready/demo/OpenAPI HTTP 200 checks,
safe missing-key chat failure and all five PostgreSQL scenarios. The reader-only
job imported LangGraph 1.2.14 on Python 3.14.8, ran as UID 10001, and contained
neither the local plan nor secrets. Temporary containers, volumes, source and
secrets were removed. The main API was rebuilt with the new workflow and left
healthy; live/ready/demo/OpenAPI returned HTTP 200. The local plan and `.env`
remain Git-ignored; a scan of all 15 changed/untracked files found no local secrets.

### Live LangGraph regression

One explicit live LangGraph regression on 2026-10-08 returned `verified=true`:
three Responses requests, three successful tools, one SQL attempt, no repairs,
and executed revenue/final fact `336080.07` EUR with the revenue citation.
The result included 14 local node transitions ending in `finish`. Reported usage
was 6721 input and 316 output tokens, plus 10 query-embedding tokens; the observed
run took 6259 ms. Its uncached cost estimate is $0.00646295 at the same dated
prices. Combined known usage for the recorded runs is estimated at $0.01282626,
excluding initial document ingestion and any cached-input discount. These are
usage-based estimates, not an invoice or account billing limit. Clarification
and repair behavior were verified offline, not through additional paid questions.

## Documentation reorganization — 2026-10-08

Detailed guides and this verification record moved from the root README into
`docs/`. The README shrank from 716 to 59 lines. A documentation index and code
map provide development context, and AGENTS.md directs contributors to them.
Outdated claims about missing LLM dispatch and unverified live access were
corrected to match the existing stage 5 implementation and recorded evidence.

All local Markdown links and anchors were checked. All 21 original fenced
command/example blocks were preserved; 26 shell blocks passed `bash -n`.
A secret scan of the 12 documentation/instruction files found no local passwords
or API keys. `git diff --check` passed. This was a documentation-only change;
application tests, Docker setup and paid API checks were not rerun for that
documentation change.

## Stage 6

Checks on 2026-10-08 passed: 205 offline, 71 PostgreSQL and 18 Chromium browser
tests (294 total), Ruff lint/format, JavaScript syntax, lockfile validation and
Alembic metadata checks. The browser tests use a real temporary FastAPI HTTP
server with explicitly labeled offline chat answers; they never invoke providers.
They verify exact Decimal/large-integer strings, NULL, empty/truncated results,
SQL and source disclosures, literal rendering of hostile HTML, clarification,
unsupported/missing-context responses, UTF-8 limits, duplicate submission, busy
HTTP responses, stale-result removal, network/malformed-response errors, browser
timeout and metadata reload. Desktop and 390px mobile screenshots were inspected,
and a wide result table stayed scrollable without overflowing the page.

A fresh source copy/new Docker volume with temporary passwords passed migration,
role provisioning, deterministic seed/control verification and HTTP checks for
health/demo/OpenAPI, `/` and all UI assets. Missing-key chat returned its safe
failure without a provider request. Five existing PostgreSQL workflow scenarios
also passed against the fresh database. Reader credential isolation, non-root
execution, secret/plan exclusion and absence of Playwright in the production image
were checked. Temporary containers, volumes, source and secrets were removed.
The main API was rebuilt with the UI and left healthy.

Playwright 1.63.0 is pinned in an optional `browser` dependency group. Chromium
153.0.8010.12 ran on the local Python 3.14.8 setup. Only Playwright and pyee were
added to the lockfile; all existing versions were preserved. Runtime dependencies
were unchanged. The implementation uses the documented
[FastAPI static mount](https://fastapi.tiangolo.com/tutorial/static-files/) and
[Starlette file response](https://starlette.dev/responses/); browser setup follows
the [Playwright library](https://playwright.dev/python/docs/library).

### Live browser acceptance

One real browser submission through the page, FastAPI, OpenAI and PostgreSQL
returned `answered` with the expected fact `336080.07` EUR, executed SQL and the
Revenue source in `knowledge/metrics.md`. SQL/source disclosures and the answer
were inspected at desktop and mobile widths. No browser script errors occurred.
This establishes one live revenue scenario; failure-state browser tests used
offline answers and do not establish broader semantic accuracy.

The temporary live-check server capped Responses input at 36000 bytes and output
at 1800 tokens to fit the remaining approved $0.05 budget. These test overrides
did not change `.env` or the normal API budgets. Actual usage was three Responses
requests, 6497 input/288 output tokens and 33892 attempted input bytes, plus one
query embedding using 16 tokens (119 bytes). The workflow made three successful
tool calls, one SQL attempt and no repairs; observed duration was 7804 ms.
At the previously recorded dated prices, uncached estimated cost is $0.00616907;
combined known usage for the recorded runs is $0.01899533, excluding the author's
initial ingestion and any cached-input discount. This is an estimate, not an invoice.

## Stage 7

Final local checks on 2026-10-08 passed: 321 tests
(231 offline, 72 PostgreSQL, 18 Chromium). The affected evaluation/logging group
also passed all 27 targeted tests after the final grader changes.
Ruff lint/format (69 Python files), JavaScript syntax, lock validation and
`git diff --check` passed. No runtime or locked package version changed.

The twenty-case **offline_scripted_postgres_evaluation** passed 20/20 cases and
15/15 expected SQL tables, including empty and undefined results. Required-heading
recall was 1.0 and mean best reciprocal rank 0.7239583333333334, using labeled
gold-heading one-hot vectors and scripted searches. This measures actual pgvector
ranking/source coverage under that fixture, not semantic embedding quality.
The two expected terminal failures were deadline_exceeded and
sql_retry_budget_exhausted. SQL repair and rejected-write recovery each made two
attempts/one repair; exhausted recovery stopped at three attempts/two repairs;
the deadline case dispatched no tools. Five extra dangerous SQL probes were rejected.
The checked-in expected values remain independent of executed SQL.

Logging tests captured actual JSON boundaries for CLI/API success, validation,
busy responses, unexpected exceptions and concurrent requests. Credentials and
newlines injected into questions, SQL/results, sources, identifiers and exceptions
were absent from summaries and sanitized failure responses. Server request IDs
were correlated with response headers/body; client IDs were ignored. Tokens and
counts retained their typed values, while unknown model/error identifiers were
removed. Docker and documented host startup disable arbitrary URL access logs.

A fresh source/new Docker volume with temporary passwords passed migrations,
roles, seed/control checks, twenty-case offline evaluation and API/root/assets
HTTP checks. Missing-key chat returned a safe category and matching request ID,
with no provider request. Five existing PostgreSQL workflow tests and the new
complete evaluation test passed against that fresh database. Non-root execution,
reader-only ask job credentials, secret/plan exclusion and absence of Playwright
were checked. Temporary containers, volumes, source and secrets were removed.

The new GitHub Actions workflow has offline, PostgreSQL and browser jobs with
no API key, and publishes only the labeled offline evaluation report.
Hosted [CI run 37830359113](https://github.com/itsvigun/querylens/actions/runs/37830359113)
passed all three jobs on snapshot `4078992effb581f731096bc74d4c6f23cad079cf` in
`verify/stage-7`. The offline evaluation artifact was uploaded successfully.
The tested snapshot contains the final application/evaluator/test/workflow code;
subsequent edits only record this evidence in documentation and the local plan.
During that CI verification, main was at stage 6 commit `465e377`, with the
stage 7 working changes captured in the separate verification branch.

The main Docker API was rebuilt with the final code and left healthy. Root, assets,
health, demo and OpenAPI returned HTTP 200. An invalid chat body returned HTTP 422
with a valid request ID and exactly one sanitized JSON log; arbitrary URL access
logs were absent. No provider request was made. The local offline report is
`artifacts/evaluation.json`; it is Git-ignored and contains only synthetic results.

At initial stage 7 completion, no paid evaluation had run. The author chose **offline only** when
offered a separately budgeted sixteen-question live run. The OpenAI Docs skill
was used to verify current official model pricing for that unexecuted proposal;
no model, API adapter, key, pricing code or account setting changed. The earlier
smoke-test budget was not spent again. That initial decision was superseded by the bounded authorization below; the
offline pass count remains separate from live model accuracy.


### Bounded live evaluation — 2026-10-08

The author subsequently authorized a live evaluation with a $0.10 budget.
Stage 7 was committed locally as `1c2f303` before the run. The application,
provider adapter, questions, references and grading policy were unchanged from
the CI-tested implementation. A two-case subset was chosen to fit a conservative
reservation within the new budget; the full sixteen-case live suite was not run.

```bash
uv run --locked python -m scripts.evaluate --live --cases arpu arppu \
  --max-input-bytes 96000 --max-output-tokens 5000 \
  --max-embedding-input-bytes 8000 \
  --output artifacts/live-arpu-arppu-2026-10-08.json
```

Each question received 48000 input bytes and 2500 output tokens; embeddings shared
an 8000-byte allowance. Official prices were rechecked using OpenAI Docs:
[GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) at
$0.75/M input and $4.50/M output, and
[text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small)
at $0.02/M input. Treating admitted bytes as conservative token allowances gives
$0.09466 for the selected limits. This local reservation is not an account billing
control or a hard wall-clock guarantee; normal SDK retries remained disabled.
The key and compatible existing index were checked without printing secrets;
there was no ingestion, reindexing or settings change.

| Case | Executed row | Expected ratio | Result |
|---|---|---|---|
| `arpu` | `336080.07`, `9501`, `35.37` | `35.37312599` | Answered; strict precision and source coverage failed |
| `arppu` | `336080.07`, `3396`, `98.96` | `98.96350707` | Answered; strict precision failed |

Both answers preserved fact-to-SQL-cell provenance and the correct revenue and
denominators. The returned ratios have two decimal places, while the suite
compares at eight. The questions did not explicitly request eight-place precision,
so this is a result-contract mismatch; it does not by itself establish a wrong
underlying denominator. ARPU also retrieved/cited two of its three required
headings; ARPPU covered both required headings. The report stores coverage counts,
not individual retrieved/cited headings, so it does not establish which ARPU
heading was missing. Overall definition recall was 0.8333333333333333 and definition MRR
0.5555555555555556. The strict report records **0/2 passed**, exits 1 and retains
both failures. There were no workflow error categories or SQL repairs
reported in the scored results. No paid rerun was performed to replace this evidence.

Actual usage: six Responses requests, 13497 input and 1023 output tokens, complete
usage reporting, and 68573 attempted input bytes. Two query embeddings used
32 tokens / 195 bytes. Durations were 6772 ms (ARPU) and 5426 ms (ARPPU), not a
latency benchmark. At the dated uncached prices, estimated usage cost is
**$0.01472689**, below the authorized $0.10, excluding any cached-input discount
and taxes; this is an estimate, not an invoice. The full report is in the ignored
`artifacts/live-arpu-arppu-2026-10-08.json` and is not a CI artifact.

Follow-up: make ratio precision explicit in evaluation questions or define a
reviewed rounding tolerance; verify all required definitions are retrieved and
cited, and include individual source headings in future diagnostic reports. Preserve this original report and independent gold values
when comparing a later change. These two sampled cases do not measure the whole
suite's accuracy, and the offline baseline remains separately labeled.

## Stage 8 preparation — 2026-10-09

Implemented local deployment preparation; **no public URL, Railway resource,
cloud backup/restore or deployed live acceptance is verified**. Account access,
hosting budget and a separate paid ingestion/five-question/public-chat allowance
remain pending. No provider calls were made in this session.

- Railway API, offline foundation-job and explicit paid-ingestion TOML files,
  reviewed against the current official config/HTTPS/volume documentation.
  TOML parsing passed; direct JSON-schema retrieval returned HTTP 403, and these
  configurations have not been accepted by an actual Railway deployment yet.
- `scripts.serve` supports a dynamic `PORT`, disables Uvicorn access logs and
  forwarded-header trust, and does not run data/provider jobs. Docker remains
  non-root. Setup is an explicit fail-fast job with sanitized step/status output;
  ingestion is separate, never an automatic startup/pre-deploy side effect.
- Migration `0004_demo_controls` adds the separate operations ledger. The optional
  fourth role can operate counters/leases and read policy/migration metadata, but
  cannot change policy, access analytics/knowledge or create relations.
- Public HTTP admission checks a shared transactional policy fingerprint, fixed
  UTC-minute rate, durable active leases and UTC-month reservation before provider
  creation. Unknown usage/crashes never reclaim reserves; admin recovery preserves
  charges. Default reservation is $0.114320 with dated standard prices and existing
  input/output/embedding caps, not a provider invoice or account billing guarantee.
  Policy changes preserve counters and refuse active leases. Disabled public
  controls on Railway fail startup. The local default remains disabled, with a
  zero configured public budget.
- HTTP 413 enforces a 16384-byte body limit before parsing, including chunks;
  the 2000-byte question bound remains. Public busy/rate/budget errors are explicit
  HTTP 429 categories, policy/storage failures HTTP 503. Local and shared public
  busy responses include a retry hint. UI messages remain literal, with no
  automatic retry. Settings validation text hides secret input values.

Final checks: **354 passed** (253 offline, 80 PostgreSQL, 21 Chromium). New tests
cover competing gates, persistent charges, no automatic crash recovery/refund,
policy mismatch/zero budgets, minute rollover, separate monthly allocations,
lock timeout/failed cleanup, role permissions, public HTTP without owner/provider
credentials, bounded bodies, safe setup failures and browser limit messages.
The operations integration fixture refuses a populated ledger before cleanup;
it must not be run against a live/public ledger.

Ruff lint/format (78 Python files), JavaScript syntax, locked dependency check
(65 packages, unchanged), Alembic drift check and Git whitespace check passed.
CI receives only an additional disposable demo-role password; new hosted CI was
not run or claimed. The earlier stage 7 hosted run remains historical evidence.

An isolated source copy, fresh PostgreSQL volume and five generated temporary DB
passwords followed the documented Docker setup: migrate → roles → seed → control
verification → API. UI/assets/demo/health/OpenAPI returned 200. Offline evaluation
passed 20/20 with scripted providers/gold-heading stub vectors. The explicit
foundation job was also repeated successfully. Its first attempt exposed missing
role secrets in the chosen Compose job environment; a dedicated `deploy-setup`
environment corrected this while retaining the smaller `demo-policy` environment.

A separate public container then ran on **PORT 8123** with only analytics reader,
knowledge reader and demo-control passwords, an empty OpenAI key, and no owner or
writer credentials. Readiness passed; a chat returned the safe `missing_api_key`
error without constructing a paid provider client. The ledger retained one
114320-micro-USD conservative allocation and no active lease. Stopping/restarting
that API and restarting the fresh DB preserved the synthetic fingerprint and
exact monthly counters. This was a local missing-key exercise, not hosted/live AI
acceptance. The harness normalized case-insensitive HTTP header names after an
initial assertion mismatch. Temporary containers, volume, source and secrets
were removed; the main demo database/default index were preserved.

The main DB is migrated/provisioned at `0004_demo_controls`. Its operations ledger
is empty after tests; the real default index retains 25 nonzero 1536-dimensional
small-model vectors and corpus hash
`575c62529847786fdb4875e155b03773b49e75713e89ec2660b2f2675b1af653`.
A random demo-control password was added only to the ignored mode-600 local `.env`,
without displaying it. The README screenshot is the actual local initial UI state,
visually inspected, with no question/model answer and no chat request.

Remaining stage 8 acceptance: approved hosting/access/budgets, actual HTTPS URL,
persistent real embedding index after a hosted restart, configured/tested backups,
and five deployed live prompts with independent values/source evidence, bounded
failures and actual usage. The original strict ARPU/ARPPU failures are preserved;
no paid rerun or changes to evaluation questions/gold values were made.

Final local report: `artifacts/evaluation-stage8-offline-2026-10-09.json`,
20/20 scripted/stub cases, 15/15 metric tables, definition recall 1.0 and MRR
0.7239583333333334; this does not establish model semantic quality. The main
Docker API was rebuilt with the final public busy-response change and is healthy;
UI/assets/demo/health/OpenAPI returned 200, malformed chat 422 and oversized body
413 with generated IDs. A scan of 38 changed/new files found no matches for actual
local secret values; 148 repository documentation link paths resolved.

## Railway dashboard inspection — 2026-10-11

Read-only inspection found the initial API startup failure
`Railway requires public demo controls`. A later deployment showed Online/Active,
but no public domain or configured readiness healthcheck. The service settings
reported that new services cannot opt into Config as Code; the deployment guide
now gives explicit dashboard settings rather than assuming the TOML files apply.
This restriction was also verified against Railway's official documentation.

The user subsequently created `db` and reported a new volume. The inspected UI
showed `pgvector-volume`, the three PostgreSQL variable names, and changes still
being deployed. This does not verify database readiness, migrations, roles, seed,
knowledge ingestion or a public URL. No secrets were revealed, remote settings
changed, setup job executed, or paid provider calls made by the agent. Only
documentation changed; application tests were not rerun for these edits.

Opening the new database deployment logs then revealed repeated `initdb` failures:
the mounted `/var/lib/postgresql/data` contains `lost+found`. An Online badge
appeared during restart attempts and did not establish database readiness. The
guide now requires `PGDATA=/var/lib/postgresql/data/pgdata` for a fresh volume.
The hosted fix has not been applied or verified by the agent; setup remains pending.

Later on 2026-10-11 the user supplied PostgreSQL's `ready to accept connections`
line. Read-only inspection then showed `db` Online and a Completed setup deployment
with all five `migrate`, `provision`, `seed`, `verify`, `policy` steps reporting
`ok`. This establishes the hosted foundation job passed. The original API service
had been repurposed as `setup`; the canvas showed only `setup` and `db`, so a
separate API service still needs configuration and readiness verification. The
guide now provides scoped API references to the matching role passwords. Public
HTTPS, knowledge ingestion, restarts, backups and paid answer acceptance remain
pending. The agent only inspected the UI and changed local documentation.

The separate `querylens` API deployment was then inspected as Active/successful.
Its deployment details showed `python -m scripts.serve` and `/health/ready`;
startup logs confirmed Uvicorn listening on port 8080. This is foundation
deployment evidence, not a direct public HTTP response or AI acceptance. The
effective retry count is ten, not the recommended three; no agent setting change
was made. The service remains unexposed.

Local `uv run --locked python -m scripts.ingest --dry-run` passed with 25 chunks,
15942 bytes and the unchanged corpus hash. The official small embedding model
price was reviewed on 2026-10-11 at $0.02 per million input tokens. With the
existing 250000-byte attempted-input cap, the conservative model-cost bound for
one ingestion execution is $0.005 excluding taxes/other callers. A separate
$0.01 ingestion allowance was requested; no paid call or hosted ingestion was
executed by the agent. The deployment guide contains the reviewed scoped job
configuration and a dry-run command while that allowance is pending.

## Public UI/API foundation smoke — 2026-10-11

The user generated and supplied
`https://querylens-production-f241.up.railway.app/docs`. Direct HTTPS GET checks
returned 200 for `/docs`, `/openapi.json`, `/`, `/health/live`, `/health/ready` and
`/demo`. Swagger HTML contains its UI bundle; OpenAPI identifies QueryLens and
the four expected API paths. Readiness returned `status: ready` with `database`,
`migrations` and `pgvector` all true. Demo metadata matches synthetic-v1,
2026-10-01 UTC and EUR. All three same-origin UI assets (`app.css`, `app.js`,
`icon.svg`) also returned 200. The UI HTML was checked; this smoke did not run
browser interactions or claim deployed AI answer quality.

The public URL is now recorded in the root README and context/deployment guides.
Public exposure precedes ingestion to satisfy the user's request to view the
page first; it does not complete stage 8. No chat POST, ingestion or provider call
was made. Separate ingestion/public-chat allowances, hosted real index, bounded
live answers, restart persistence and backup restore verification remain pending.

## Hosted knowledge ingestion — 2026-10-11

The user executed the separate Railway ingestion job. Read-only browser inspection
of its Completed deployment logs confirmed `status: indexed` at 19:34 GMT+2:

- Index `default`: 25 chunks, 25 embedded, 0 reused and 0 removed.
- Provider `openai`, model `text-embedding-3-small`, dimensions 1536.
- Two embedding requests reported 3362 prompt tokens.
- Corpus SHA-256:
  `575c62529847786fdb4875e155b03773b49e75713e89ec2660b2f2675b1af653`,
  matching the local corpus.

This establishes hosted live ingestion, not semantic retrieval or deployed chat
acceptance. The agent did not rerun ingestion, enter/reveal keys or make paid
provider calls. Public-chat budget selection and API key configuration are next;
hosted live answers, restart persistence and backup recovery remain pending.

## Hosted public-chat allocation — 2026-10-11

The author explicitly approved $1/month for the public chat. Railway CLI 5.64.2
was linked to the expected project/production environment. Before mutation,
API/setup settings and the stored policy matched the zero allocation, and there
were no active leases. The API had no OpenAI key.

The API deployment was stopped, then `PUBLIC_CHAT_MONTHLY_BUDGET_USD=1` was set
on API and setup with automatic deployment suppressed. An explicit administrator
operation called the existing `scripts.demo_policy.configure` through a local
SSH tunnel to the private DB, using scoped owner credentials held only in memory.
No owner credentials were added to the API. The updated fingerprints matched;
monthly/rate records and leases were unchanged. The default request reservation
remains 114320 micro-USD, allowing at most eight questions per UTC calendar month.

The automatic `railway connect --tunnel-only` path exited unsuccessfully before
any mutation; direct SSH forwarding worked. Removing the API deployment left
`latestDeployment` null, requiring the administration helper to handle that
state before continuing. Redeployment from the GitHub source used the same
commit `046f7863310492c29874779cfdda84a3775cdada`.

Deployment `827db590-06ca-4a7a-a9c8-9bacb440b86f` reached SUCCESS. Public
`/health/ready` returned 200, `status: ready`, and all three checks true. A
read-only check inside the new API container confirmed monthly USD 1, matching
DB policy, zero leases and no monthly charge records. The API key remains absent;
no chat POST/provider call was made. Current model prices were rechecked against
the official [mini model](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
and [embedding model](https://developers.openai.com/api/docs/models/text-embedding-3-small)
pages and match the versioned policy. Hosted AI answer acceptance remains pending.

## Database overview diagnosis and local fix — 2026-10-11

After the author added the API key and redeployed, Railway deployment
`b78070a8-774d-46d5-b6e3-ce27acd54dd9` was SUCCESS on commit `046f786`.
Read-only sanitized request summaries showed three `ungrounded_answer` failures
with two tool calls and zero SQL attempts, alongside one `answered` request with
three tool calls and one SQL attempt. Logs omit question text, so this establishes
the observed failure pattern rather than matching a particular screenshot by
its question. Inspection of `resolve_answer` confirmed that an answered result
requires schema, retrieved sources and successful SQL. Overview responses after
only the context tools are rejected by that contract.

The local prompt now explicitly supports full-dataset overviews without a metric
or period, requesting SQL row counts/time bounds with referenced facts. Answer
validation, SQL permissions, workflow budgets and public policy are unchanged.
The UI now explains provenance failures and always offers Run details for errors;
it displays only recognized categories and hides unknown category payloads. The
input hint also permits dataset questions.

Checks completed:

- Ruff lint/format checks for the changed Python files and `git diff --check`.
- `uv run --locked pytest tests/test_llm.py tests/test_workflow.py tests/test_ui.py -q`:
  63 passed.
- `QUERYLENS_BROWSER=1 uv run --locked --group browser pytest tests/test_ui_browser.py -q`:
  26 passed after the grounding-message changes.
- After adding the unknown-category regression and changing the input hint,
  the focused browser run with `-k 'unknown_failure_category or answer_evidence_precision'`
  passed all three cases (24 deselected), including desktop/mobile rendering.

These checks use offline providers/browser fixtures and do not prove semantic
model compliance with the revised prompt. The local fix has not been committed,
pushed or deployed, and no paid provider call was made by the agent. Hosted
overview acceptance must be checked after deployment within an explicit allowance.
