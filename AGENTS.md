# QueryLens — repository instructions

## Project context

QueryLens is a portfolio project for Backend / Applied AI Engineering. It will
answer business questions using documentation retrieval, LLM tool calling, and
read-only SQL over synthetic PostgreSQL data. The author should be able to explain
the implementation and its limits in an interview.

If available, read the local, Git-ignored `QUERYLENS_PLAN.md` at the start of each
session, especially its checklist and handoff, then inspect the current files.
The plan describes intended capabilities; the implementation and checks establish
what actually works. The plan is kept only in the author's local workspace and
is not included in repository clones.

Read `docs/README.md` and `docs/architecture.md` for shared development context,
then the relevant topic guide and its source/tests before changing behavior.
Use `docs/setup.md` and `docs/testing.md` for exact commands, and the latest
section of `docs/verification.md` for checks actually completed. The guides
provide context in clones without publishing the local plan. Keep contributor
documentation in `docs/`; `knowledge/` is the ingested business corpus.

## Working style

- Discuss progress and explain important decisions in Ukrainian. Write code,
  comments, UI text, and repository documentation in English. Keep the existing
  Ukrainian plan and handoff in Ukrainian.
- Write commit messages in English.
- Work on one milestone at a time and finish its acceptance checks. A request to
  "continue" means the next unfinished stage in the plan unless directed otherwise.
- Keep the structure simple. Create modules as they become necessary; do not
  scaffold empty modules or abstractions for all future stages.
- Explain new AI concepts through the code being implemented.
- After each session, update the plan's checklist and handoff with completed work,
  checks actually run, remaining work, decisions, and blockers. Record reasons for
  changes to the plan. Mark a stage complete only after its acceptance criteria pass.
- Summarize the outcome, how to run or verify it, and any unresolved limitations.

## Architecture and scope

- Use Python, FastAPI, PostgreSQL with pgvector, SQLAlchemy, Alembic, and Docker
  Compose. Add dependencies when the relevant stage needs them.
- Start with OpenAI and verify the current official Responses API documentation
  when implementing the adapter. Add Anthropic after the working MVP.
- Implement real provider tool calls with validated arguments and server-side
  dispatch. Use LangGraph for bounded workflow orchestration at its planned stage.
- Keep LLM and embedding provider settings separate. Version the embedding model
  and dimensions with the index; changing the vector space requires reindexing.
- Run migrations, seed generation, and knowledge ingestion as explicit commands,
  separate from web server startup. Make seed and ingestion reproducible.
- A single PostgreSQL instance with separate analytics and knowledge schemas is
  sufficient. A minimal UI served by FastAPI is sufficient for v1.
- Follow the suggested layout in the plan as modules are implemented: `app/`,
  `knowledge/`, `migrations/`, `scripts/`, `evals/`, and `tests/`.
- Defer streaming, session history, advanced retrieval, and additional providers
  until their planned stages. Keep arbitrary database connections, public document
  uploads, billing, Kubernetes, and microservices outside MVP scope.
- Verify package compatibility, model availability, hosting capabilities, and
  pricing when making the corresponding implementation decision.

## Data and answer correctness

- Use synthetic data only. Use timezone-aware timestamps and UTC periods, EUR,
  and decimal/NUMERIC money values. Fix the seed and demo reference date.
- Resolve relative periods against the visible demo reference date.
- Follow the metric definitions in the plan and knowledge base: revenue includes
  completed orders only; ARPU uses active users; ARPPU uses paying users.
- Make denominators and time windows explicit. An unavailable denominator yields
  an undefined value. Clarify ambiguous periods or conversion windows.
- Derive answer numbers from executed queries and include SQL, results, sources,
  and relevant limitations. Explain segment contributions without claiming causality.
- Label synthetic, mocked, or recorded output accurately. Claim integrations,
  deployment, accuracy, or performance only when supported by actual verification.

## SQL and LLM safety

- Treat generated SQL, retrieved documents, and tool output as untrusted input.
  Permissions and tool availability are enforced by backend code and PostgreSQL.
- Execute analytics queries with a separate role limited to SELECT on allowed
  analytics tables/views and a server-controlled read-only transaction. Keep
  migration and ingestion credentials out of the SQL tool.
- Validate SQL with an AST parser: one read query, allowed relations/functions,
  including nested queries and CTEs. Reject writes, write CTEs, DDL, COPY,
  SELECT INTO, locking clauses, and multiple statements. Prefix checks and regex
  alone are insufficient.
- Enforce database/LLM timeouts, result row and byte limits, request deadlines,
  and tool/retry budgets. Report truncation and bounded failures explicitly.
- Return structured tool results and sanitized errors. Never expose credentials
  through code, Git, documentation, logs, tool output, or LLM context.
- Keep secrets server-side and use `.env.example` for placeholders. Exclude local
  secret files from Git and Docker build contexts.

## Verification and commands

The current foundation uses uv, Python 3.14.8, and a development dependency group for
pytest, HTTPX2, and Ruff. See `docs/verification.md` and the local plan's handoff
for checks actually completed.
Establish and document exact setup, run, migration, lint, test, and evaluation
commands in the relevant `docs/` guide as stages are implemented. Keep `README.md`
limited to project purpose, current status, quickstart and documentation links.
Update guides when behavior changes and append actual verification evidence;
do not present planned commands as commands that have already passed.

Stage 1 includes analytics Core metadata, migrations, explicit role provisioning,
deterministic seed generation, and control SQL verification. Use the fixed
synthetic-v1 reference date (2026-10-01 UTC). Database integration tests require
the dedicated, migrated, provisioned, and seeded demo database; metric fixtures
are rolled back and disposable knowledge probes are removed. Keep the checked-in
reference values independent of executed SQL when changing the dataset.

Stage 2 adds reviewed schema metadata and the validated SQL tool. Keep its exact
SQLGlot version pinned; parser upgrades require policy and generated-SQL review.
Use `scripts.query` for local smoke checks, not a public arbitrary-SQL endpoint.
The tool must use only AnalyticsSettings, validate all AST scopes before database
access, and preserve structured failure/truncation metadata. Real PostgreSQL
tests cover transaction identity, row/byte limits, statement/lock timeouts,
caller deadlines, and recovery. Do not describe the cooperative tool deadline
as a hard network wall-clock guarantee or returned-byte limits as database memory
limits. Stage 4 supplies a first bounded loop; stage 5 moves orchestration to LangGraph.

Stage 3 uses explicit `scripts.ingest` and `scripts.search` jobs, with separate
knowledge writer/reader credentials. Keep vector-space settings and application
index/chunker versions with each named corpus. Setting changes require explicit
reindex; ingestion must atomically preserve the previous index on failure and
reuse unchanged embeddings. `scripts.ingest --dry-run` needs no DB/API access.
Offline provider tests and PostgreSQL tests with labeled stub vectors establish
contracts/storage/safety, not semantic quality. Run `scripts.verify_retrieval
--live` separately with an explicit budget/key before marking live acceptance
complete. Foundation health readiness does not yet represent end-to-end AI
readiness; retrieval itself checks index compatibility.

Stage 4 uses `app/llm/` and validated `app/tools/dispatch.py` with the Responses
API, three strict function schemas, stateless output replay, and zero SDK retries.
Keep LLM settings independent of embeddings. `scripts.ask` and `/api/chat` use
only dedicated readers in tools; startup/health must not invoke providers.
Numeric facts reference actual SQL cells and source IDs; validate them server-side.
This proves provenance, not semantic correctness of chosen queries or prose.
Track actual usage, bounded failures, deadlines and attempts. Run
`scripts.verify_tool_calling --live` separately with an explicit
budget/key before marking stage 4 live acceptance complete.

Stage 5 uses `app/llm/workflow.py` with a sequential LangGraph StateGraph, fresh
state per question, conditional transitions, separate SQL repair and total-attempt
budgets, a request deadline and a graph step guard. Keep the existing Responses
adapter and server-side dispatch/SQL controls. Clients and secrets stay outside
state; do not add checkpoint persistence or external tracing. LangSmith tracing
is explicitly disabled even if shell variables enable it. Return sanitized node
transitions and counters alongside tool trace and executed results. Exercise
correct queries, clarification, unsupported questions, SQL repair, exhausted
budgets and deadlines offline; use real PostgreSQL for SQL error/recovery paths.

- Use pytest and Ruff. Run checks relevant to the change and report their results.
- Keep offline tests and CI deterministic and independent of paid API keys. Use
  stub providers for offline workflow tests; keep live smoke tests/evaluation
  separate with an explicit budget.
- Test SQL permissions, runtime timeouts, and PostgreSQL/pgvector behavior against
  PostgreSQL. Mocks alone do not establish database safety.
- Evaluate result values rather than SQL string equality. Cover metric definitions,
  date boundaries, empty results, undefined denominators, dangerous SQL, prompt
  injection, recovery, exhausted budgets, and answer/result consistency.
- Verify a fresh setup using `docs/setup.md` before marking local setup complete, and
  run live deployment smoke checks before marking deployment complete.
