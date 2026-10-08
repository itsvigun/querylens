# Evaluation

[Documentation index](README.md)

The versioned suite in [`evals/cases.json`](../evals/cases.json) contains twenty
questions over synthetic-v1 and the fixed 2026-10-01 UTC reference date. Expected
values are copied from the independently calculated Python references in
[`scripts/reference_values.json`](../scripts/reference_values.json), not from
executing candidate SQL. Dataset/control verification runs before evaluation;
a mismatched database stops the run.

## Offline evaluation

Prepare the dedicated demo database using [setup](setup.md). Then run:

```bash
mkdir -p artifacts
uv run --locked python -m scripts.evaluate --offline --output artifacts/evaluation.json
```

Alternatively, use the Docker job, which has analytics/knowledge readers and the
knowledge writer for its temporary index, no owner credentials or provider key:

```bash
docker compose run --build --rm evaluate-offline
```

This executes the real LangGraph, server dispatch, SQL AST validation, read-only
PostgreSQL queries, and pgvector retrieval. A **scripted provider** supplies reviewed
calls; **gold-heading one-hot vectors** supply deterministic retrieval geometry.
No API key is used, even if a real key exists locally. It proves contracts, values,
permissions and recovery for these scenarios; it does not measure LLM reasoning or
embedding semantic quality.

A disposable named index contains copies of the business corpus plus a labeled
prompt-injection fixture. Its creation/cleanup uses only the knowledge writer;
SQL uses only AnalyticsSettings. Cleanup removes that index on success or failure.
The main default index is preserved. Injection instructions are data; the scripted
provider attempts a DELETE, which the SQL guard rejects before a repaired read.
Five additional dangerous SQL probes exercise multiple statements, write CTE,
SELECT INTO, a filesystem function, and a knowledge relation. Existing PostgreSQL
integration tests separately establish the database role and transaction controls.

## Cases and scoring

| Coverage | Cases |
|---|---|
| Revenue and time windows | September, last month, previous complete calendar week |
| Denominators | Active users, ARPU, ARPPU |
| Tables | Country revenue and subscription churn |
| Cohorts | Observed August conversion and unobserved September conversion |
| Empty/undefined | June revenue, undefined ARPU, empty country table |
| Non-answers | Ambiguous conversion window, unsupported MRR, missing marketing context |
| Bounded workflow | SQL repair, injection/write rejection, exhausted repairs, deadline |

Fifteen cases have expected SQL tables, including empty results and the two repaired
queries. Numeric strings are compared as Decimal at eight decimal places; boolean,
NULL and text values remain distinct. Row order is ignored, but column order, row
multiplicity and all expected cells matter. Ratios are fractions, not percentages.
The table questions specify their column order; an otherwise equivalent layout
can fail this deliberately narrow result contract. Expected cells must appear in
final facts with their multiplicity. Every fact must equal its referenced SQL cell
and preserve the undefined flag. Different SQL strings can pass with the same
correct values. A self-consistent answer derived from a wrong query fails values.

Definition recall measures required **path + heading** coverage across all returned
search-tool results, each bounded to top three. Definition MRR averages the best
reciprocal rank of each required heading across those searches. Citation recall
measures the headings in the answer's selected sources separately. These checks
measure source coverage, not the correctness of prose or whether a definition was
applied correctly. In offline mode gold-heading vectors and scripted searches make
this a retrieval contract check. Ties and the hostile fixture can lower MRR.

Expected errors are successes when the correct category and bounds are observed.
The JSON report separately lists pass/fail, metric correctness, fact provenance,
status counts, failure categories, SQL attempts/repairs, actual rows, timings,
usage, corpus/chunker/index versions and package/model versions. A nonzero exit
status signals a failed case or setup failure; failed cases remain in the report.
Reports are created as new files and never overwrite previous evidence.
`artifacts/` is ignored by Git and excluded from Docker builds.

## Live evaluation

Sixteen cases are live-eligible. The four fault-injection cases are offline-only.
Live mode uses the existing OpenAI adapter, real embeddings and the compatible
configured index; it does **not** ingest, reindex or automatically rerun failed
questions. Select cases and agree on paid usage before running. Example for a
single revenue question:

```bash
uv run --locked python -m scripts.evaluate --live \
  --cases revenue_september \
  --max-input-bytes 40000 --max-output-tokens 2000 \
  --max-embedding-input-bytes 16000 \
  --output artifacts/live-revenue.json
```

These flags are required positive **total** budgets. Input bytes and output tokens
are divided equally among selected questions, rounded down, and capped by existing
per-question limits. An unusably small share fails settings validation before any
provider call. The shared embedder enforces the total embedding-input allowance.
Existing model/tool/SQL/retry budgets and cooperative deadlines remain active.
Input counts include serialized request/protocol allowances; returned provider
usage is authoritative. These local limits are not an account spending guarantee.
No cost number is reported, so this stage introduces no pricing configuration.

A full suite is a separate paid decision: do not reuse the small historical smoke
budget for sixteen questions. The stage 7 baseline is **offline**, and its pass
count must never be presented as live model accuracy. Even live results establish
only the sampled synthetic scenarios, without a prose judge, confidence intervals
or a latency benchmark. See [verification](verification.md#stage-7) for checks
actually run and [CI](ci.md) for the uploaded offline report.


## First bounded live result

A later $0.10-authorized run selected ARPU and ARPPU only. Both answered with the
correct revenue and denominators and preserved SQL-cell provenance, but the strict
evaluator recorded 0/2: both ratios were rounded to two decimal places rather than
eight, and ARPU covered only two of its three required source headings. The
report does not identify the missing heading. The original report and
usage are recorded in [verification](verification.md#bounded-live-evaluation--2026-10-08).
The comparison contract needs explicit question precision or a reviewed rounding
policy before treating this precision failure as semantic metric error. No expected
values, grading rules or paid results were rewritten after the run.
