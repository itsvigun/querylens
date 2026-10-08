# Knowledge ingestion and retrieval

[Documentation index](README.md)

Add `OPENAI_API_KEY` to your local `.env` for real embeddings. Keep the key out of
chat, Git, and client-side code. Complete the [setup guide](setup.md) with distinct
role passwords. For local Python, apply migrations and provision roles before ingestion:

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked python -m scripts.provision_roles
uv run --locked python -m scripts.ingest --dry-run
uv run --locked python -m scripts.ingest
uv run --locked python -m scripts.search 'How is ARPU calculated?'
```

Docker equivalents:

```bash
docker compose run --build --rm migrate
docker compose run --rm provision-roles
docker compose run --rm ingest python -m scripts.ingest --dry-run
docker compose run --rm ingest
docker compose run --rm search python -m scripts.search 'How is ARPU calculated?'
```

Dry-run reads Markdown and reports chunk count, sources, corpus hash, and input
bytes without DB/API access. No ingestion runs during API startup. `ingest`
receives only writer credentials and the embedding key; `search` receives only
knowledge reader credentials and the key. The SQL `query` job receives neither
the key nor knowledge credentials. The API serves foundation health/demo
endpoints and [chat](chat.md); only an explicit question dispatches LLM tools.

Markdown is split by ATX headings and line boundaries, splitting long lines as
needed. Each chunk includes source and heading context and is at most 2000 UTF-8
bytes. Ids/content hashes are deterministic. Metadata includes document SHA-256,
heading, ordinal, and original line range. Headings inside fenced code remain
content. This small chunker is not a complete Markdown renderer. Only repository
Markdown is ingested; no public uploads or external URLs. Bounds: 64 files,
64 KiB/file, 1 MiB/corpus, 512 chunks. Empty corpora/documents and symlinks fail.

Default embeddings use `text-embedding-3-small`, with explicit 1536 dimensions,
as documented in the official
[embedding guide](https://developers.openai.com/api/docs/guides/embeddings).
The [API](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
supports `dimensions` for third-generation models. Provider, model, dimensions,
application index version, and chunker version are stored with the corpus.
Incompatible settings fail before provider calls; changing vector space requires:

```bash
uv run --locked python -m scripts.ingest --reindex
# Docker:
docker compose run --rm ingest python -m scripts.ingest --reindex
```

Reindex replaces only the configured named knowledge index. Provider aliases can
evolve: bump `EMBEDDING_INDEX_VERSION` and rebuild when intentionally adopting a
changed space. This version does not pin an undocumented provider snapshot.

Ingestion reuses unchanged content embeddings, updates document metadata, and
removes stale chunks in one transaction. Repeating an unchanged corpus reports
`unchanged` without API calls. Provider/DB failures roll back the new snapshot.
A global advisory lock serializes explicit ingestion jobs and is held during
embedding requests. Searches see a complete previous snapshot until commit.
The cooperative ingestion deadline is 60 seconds; large or concurrent jobs may
fail rather than extend it.

Search embeds the query and runs exact pgvector cosine search in a read-only,
repeatable-read transaction over the compatible named index. It returns up to
5 sources by default (maximum 8), with source ids, paths, headings, line citations,
hashes, text, and similarity. Query input is capped at 2000 UTF-8 bytes; results
default to 16 KiB, with explicit truncation. Similarity below 0.2 is excluded;
no qualifying source yields `insufficient_context`. The threshold is a heuristic,
not a relevance guarantee; similarity is not a confidence probability. Retrieved
text is untrusted data and cannot change tools/permissions. The SQL validator
continues to exclude all knowledge relations. Retrieval itself does not generate answers;
the separate tool-calling session uses its output.

The adapter batches at most 16 inputs and disables SDK retries. UTF-8 byte count
conservatively bounds byte-level BPE tokens, avoiding runtime tokenizer downloads.
Each CLI client limits attempted input to 250000 bytes (search: 2000). Paid smoke
verification shares this budget across ingestion and queries and reports actual
provider token usage. The documented
[small-model price](https://developers.openai.com/api/docs/models/text-embedding-3-small)
on 2026-10-07 is $0.02 per million input tokens; this conservative smoke budget is
at most $0.005 at that price. This is a dated estimate, not billing measurement.
Verify current pricing/account access before running. Network timeouts remain
cooperative, as with the SQL tool.

Explicit paid verification checks revenue, ARPU, churn, and repeat ingestion:

```bash
uv run --locked python -m scripts.verify_retrieval --live
# Or:
docker compose run --rm verify-retrieval
```

This uses real embeddings and never substitutes stub vectors. Offline tests mock
provider transport; PostgreSQL tests use labeled stub geometry for vector storage,
ranking, constraints, permissions, and atomicity. Those tests do not establish
semantic retrieval quality.

The ingested business corpus is [`knowledge/`](../knowledge).
The `docs/` directory holds contributor documentation and is not part of the
default retrieval corpus. Current verification evidence is in
[verification.md](verification.md#stages-3-and-4-live-acceptance).
