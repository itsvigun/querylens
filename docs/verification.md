# Verification record

[Documentation index](README.md)

This is dated evidence, not a list of checks automatically run on every change.
Start with [stage 5](#stage-5) for the latest implementation evidence.
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
application tests, Docker setup and paid API checks were not rerun. The stage 5
checks above remain the latest implementation evidence.
