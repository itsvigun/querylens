# Database schema

QueryLens uses one PostgreSQL database. The `analytics` schema contains synthetic
business data. The separate `knowledge` schema stores document metadata and
embeddings. The pgvector extension is installed in `public`. Migrations use Alembic.

## analytics.users

| Column | Type | Meaning |
|---|---|---|
| id | BIGINT primary key | Positive deterministic synthetic identifier |
| country | VARCHAR(2) NOT NULL | DE, PL, FR, or ES; fixed synthetic country |
| registered_at | TIMESTAMPTZ NOT NULL | Registration time in UTC |
| status | VARCHAR(16) NOT NULL | active or disabled; current snapshot status |

Indexes cover registered_at and (country, registered_at). Country is constant in
this dataset; a country revenue breakdown joins orders.user_id to users.id.

## analytics.orders

| Column | Type | Meaning |
|---|---|---|
| id | BIGINT primary key | Positive deterministic synthetic identifier |
| user_id | BIGINT NOT NULL foreign key | analytics.users.id |
| amount | NUMERIC(12,2) NOT NULL | Nonnegative amount in EUR |
| currency | VARCHAR(3) NOT NULL | EUR only, enforced by a check constraint |
| created_at | TIMESTAMPTZ NOT NULL | Order time in UTC |
| status | VARCHAR(16) NOT NULL | completed, refunded, or cancelled |

Indexes cover (status, created_at) and (user_id, created_at). Only completed orders
contribute to revenue or paying-user counts.

## analytics.events

| Column | Type | Meaning |
|---|---|---|
| id | BIGINT primary key | Positive deterministic synthetic identifier |
| user_id | BIGINT NOT NULL foreign key | analytics.users.id |
| event_type | VARCHAR(32) NOT NULL | session or checkout |
| created_at | TIMESTAMPTZ NOT NULL | Event time in UTC |

Indexes cover (event_type, created_at) and (user_id, created_at). See events.md for
semantics. A user can have many events and many orders; joining both directly
can multiply rows and inflate revenue.

## analytics.subscriptions

| Column | Type | Meaning |
|---|---|---|
| id | BIGINT primary key | Positive deterministic synthetic identifier |
| user_id | BIGINT NOT NULL foreign key | analytics.users.id |
| plan | VARCHAR(16) NOT NULL | basic, pro, or enterprise |
| started_at | TIMESTAMPTZ NOT NULL | Subscription start time in UTC |
| cancelled_at | TIMESTAMPTZ nullable | Cancellation time; NULL means no cancellation |

Cancellation cannot precede the start. Indexes cover (plan, started_at),
cancelled_at, and user_id. The schema permits multiple subscriptions per user;
the initial seed uses one per subscribed user. Plan changes are not modeled.

## Constraints and ownership

Primary keys, foreign keys, nullability, money/currency, enum-like string checks,
and subscription date checks are enforced by PostgreSQL. The generator also
ensures orders, events, and subscriptions do not precede user registration;
this cross-table temporal rule is not a database check constraint.

Identifiers are assigned by the generator, so analytics tables need no sequences.
The migration owner owns the tables; reader and knowledge writer own no objects.

## knowledge indexes and chunks

`knowledge.indexes` records each named corpus's embedding provider, model,
dimensions, application index version, chunker version, corpus hash, chunk count,
and UTC update time. These fields define a vector space; retrieval rejects an
incompatible space before making an embedding request. A setting change requires
an explicit reindex. Provider model aliases can evolve, so bump the application
index version and rebuild when intentionally adopting a changed embedding space.

`knowledge.chunks` stores a stable chunk id, source path, heading, ordinal,
source line range, document/content hashes, text, dimensions, and a pgvector
embedding. Constraints enforce matching index dimensions, nonzero vectors,
valid source positions, and content up to 2000 UTF-8 bytes. No approximate vector
index is used: the small corpus uses exact cosine-distance search.

Ingestion is an explicit command with the knowledge writer. It replaces a
complete named snapshot transactionally, reuses unchanged content embeddings,
and removes stale chunks. Searches keep seeing the previous complete snapshot
until commit. Retrieved documents are untrusted context; they cannot grant SQL
permissions or add tools. Cosine similarity is not a confidence probability.

## Access roles

`querylens_analytics_ro` has CONNECT, analytics USAGE, and SELECT on exactly the
four business tables. It cannot write, create tables/temp tables, change table
definitions, assume the owner/writer role, or read knowledge data. New analytics
tables require an explicit grant after review; they are not automatically exposed.

`querylens_knowledge_writer` has knowledge USAGE and SELECT/INSERT/UPDATE/DELETE
on knowledge tables, plus sequence USAGE/SELECT. Default grants apply to future
knowledge objects created by the migration owner. It has no analytics access
or schema CREATE privilege.

`querylens_knowledge_ro` has knowledge USAGE and SELECT on knowledge tables,
including future tables created by the migration owner. It has no analytics
access, writes, sequence privileges, schema CREATE, or role memberships.
Searches use server-controlled read-only transactions and protected search path
pg_catalog, public, knowledge, because pgvector operators live in public.

All three dedicated login roles are non-superusers, with no role memberships, CREATEDB,
CREATEROLE, replication, or BYPASSRLS. Passwords are distinct and stored only in
local/server secrets. Role provisioning is a separate administrator command for
a dedicated QueryLens PostgreSQL cluster. It also revokes PUBLIC database
CREATE/TEMPORARY and public schema CREATE.

The database tool combines these grants with AST validation, reviewed
function/relation/type allowlists, server-controlled read-only transactions,
statement/lock timeouts, and row/byte limits. Every physical relation is qualified
to analytics; the tool's search path is pg_catalog. Knowledge and catalog
relations, arbitrary functions, writes, and locking clauses are rejected. The
accepted SQL subset is intentionally limited; see README.md for exact budgets
and deadline limitations. PostgreSQL built-in functions and catalogs are not a
safe arbitrary-SQL interface solely because table writes are forbidden.
