# Synthetic data, metrics and roles

[Documentation index](README.md)

## Synthetic dataset and reference date

The dataset version is **synthetic-v1**, with random seed **20261001** and a fixed
reference date of **2026-10-01 00:00:00 UTC**. It contains:

| Table | Rows |
|---|---:|
| analytics.users | 10,000 |
| analytics.orders | 20,000 |
| analytics.events | 80,000 |
| analytics.subscriptions | 3,000 |

All money is EUR and uses NUMERIC(12,2). Timestamps are timezone-aware. Last month
means September 2026; last week means the previous complete Monday-to-Monday week,
September 21 through September 27 inclusive. Both use exclusive end boundaries.
`GET /demo` exposes the configured reference date and synthetic label; it does
not check whether the data has been loaded.

Repeating seed on matching data reports `unchanged`. The full ordered dataset is
checked using SHA-256. Differing data is preserved unless replacement is explicit:

```bash
# Only for replacing this project's synthetic analytics dataset.
docker compose run --rm seed python -m scripts.seed --replace
# Or with local Python:
uv run --locked python -m scripts.seed --replace
```

Replacement is transactional and touches only the four analytics tables. Neither
seed nor role provisioning runs during web server startup.

## Database roles

Use a dedicated local QueryLens PostgreSQL cluster. PostgreSQL login roles are
cluster-wide; `provision-roles` creates/updates the fixed roles and their passwords.
It refuses role memberships and object ownership. It also revokes PUBLIC database
CREATE/TEMPORARY and public schema CREATE. Do not run it on a shared production
cluster without adapting the administration process.

| Role | Purpose and permissions |
|---|---|
| Local owner (`POSTGRES_USER`) | Migrations, provisioning, seed, and current health checks |
| querylens_analytics_ro | SELECT on the four analytics tables; no writes, DDL, temp tables, or knowledge access |
| querylens_knowledge_writer | Read/write on knowledge tables created by the migration owner; no analytics access or schema CREATE |
| querylens_knowledge_ro | SELECT on knowledge tables; no analytics, writes, DDL, or sequences |

The reader has PostgreSQL defaults for read-only transactions, a 5-second statement
timeout, a 1-second lock timeout, and UTC. These defaults can be changed by a
client; integration tests therefore also check permissions after explicitly
switching to a read-write transaction. New analytics relations require explicit
grants. Future knowledge tables/sequences inherit writer grants, and future
knowledge tables inherit reader SELECT, when created by the same migration owner.

Role passwords are not embedded in migrations or sent as plaintext SQL statements;
provisioning uses client-generated SCRAM verifiers. Dedicated passwords are passed
only to the jobs that need them. The `query` job receives only reader credentials;
owner and ingestion credentials are absent from its environment. The API has no
public arbitrary-SQL endpoint. Chat dispatches validated SQL through the analytics reader.

## Metric documentation and control SQL

Definitions and limitations are documented in:

- [Metrics](../knowledge/metrics.md): revenue, active users, ARPU, ARPPU, conversion, churn.
- [Database](../knowledge/database.md): columns, constraints, indexes, joins, and roles.
- [Business rules](../knowledge/business_rules.md): time anchor and synthetic scenarios.
- [Events](../knowledge/events.md): session/checkout meanings and aggregation limits.

Trusted, parameterized queries are in [scripts/sql](../scripts/sql). Their `:start`
and `:end` placeholders are bound by SQLAlchemy, not copied directly into psql.
`verify-data` connects as the real analytics reader and compares executed results
with [reference values](../scripts/reference_values.json), computed independently by
Python in [reference_metrics.py](../scripts/reference_metrics.py). Money is compared
exactly at two decimal places; ratios are rounded to eight decimal places.

September revenue is **336,080.07 EUR**, with **9,501 active users** and **3,396
paying users**. ARPU is **35.37312599 EUR**; ARPPU is **98.96350707 EUR**. The
June empty-period case has 0 revenue and undefined (NULL) ARPU/ARPPU.

The seed deliberately includes a Germany purchase decline and churn differences
between plans. These scenarios support correctness checks; they do not establish
causal explanations. Conversion requires an explicit observation window; the
30-day September cohort is not fully observed and yields an undefined rate.
