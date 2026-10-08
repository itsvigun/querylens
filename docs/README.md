# Documentation

Start with [architecture.md](architecture.md) for current scope, request flow,
trust boundaries and the module map, then read the guide for the area you will
change. Inspect the corresponding source and tests before implementation.
For commands and acceptance, use setup/testing; for past evidence, read the latest
section of the verification record. All commands run from the repository root.

| Guide | Contents |
|---|---|
| [Architecture and development context](architecture.md) | Implemented capabilities, design decisions, code map, limits and next milestone |
| [Setup and operations](setup.md) | Docker, host development, migrations, health and enabling chat |
| [Configuration](configuration.md) | Environment variables, defaults, credentials and bounds |
| [Data, metrics and roles](data.md) | Synthetic dataset, time anchor, seeding, PostgreSQL roles and reference values |
| [Validated SQL tool](sql-tool.md) | CLI, AST policy, read-only execution, limits and result format |
| [Ingestion and retrieval](retrieval.md) | Chunking, embeddings, indexing/reindexing, search and paid retrieval check |
| [Chat and LangGraph](chat.md) | Responses contract, CLI/API, grounding, graph transitions and budgets |
| [Web UI](ui.md) | Browser interaction, answer evidence, errors, rendering safety and UI checks |
| [Testing and acceptance](testing.md) | Offline, PostgreSQL, drift checks and explicit live checks |
| [Verification record](verification.md) | Dated local, Docker and live evidence, observed usage and limitations |

The business knowledge used by retrieval lives in [`knowledge/`](../knowledge).
These contributor guides are not ingested into the default index.
Repository working rules remain in [`AGENTS.md`](../AGENTS.md). The optional
`QUERYLENS_PLAN.md` is local and Git-ignored; this documentation provides context
for clones without publishing the author's plan.

Keep the [root README](../README.md) concise. Put new operational or implementation
details in the relevant guide. Record checks actually run separately from planned
work, and preserve the distinction between offline/stub and live evidence.
