# QueryLens — repository instructions

## Project context

QueryLens is a portfolio project for Backend / Applied AI Engineering. It will
answer business questions using documentation retrieval, LLM tool calling, and
read-only SQL over synthetic PostgreSQL data. The author should be able to explain
the implementation and its limits in an interview.

Read `QUERYLENS_PLAN.md` at the start of each session, especially its checklist and
handoff, then inspect the current files. The plan describes intended capabilities;
the implementation and checks establish what actually works.

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

The stage 0 skeleton uses uv, Python 3.14.8, and a development dependency group for
pytest, HTTPX2, and Ruff. See the plan's handoff for checks actually completed.
Establish and document exact setup, run, migration, lint, test, and evaluation
commands in `README.md` as the relevant stages are implemented. Do not present
planned commands as commands that have already passed.

- Use pytest and Ruff. Run checks relevant to the change and report their results.
- Keep offline tests and CI deterministic and independent of paid API keys. Use
  stub providers for offline workflow tests; keep live smoke tests/evaluation
  separate with an explicit budget.
- Test SQL permissions, runtime timeouts, and PostgreSQL/pgvector behavior against
  PostgreSQL. Mocks alone do not establish database safety.
- Evaluate result values rather than SQL string equality. Cover metric definitions,
  date boundaries, empty results, undefined denominators, dangerous SQL, prompt
  injection, recovery, exhausted budgets, and answer/result consistency.
- Verify a fresh setup using the README before marking local setup complete, and
  run live deployment smoke checks before marking deployment complete.
