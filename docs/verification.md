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
