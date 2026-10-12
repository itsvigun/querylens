"""Public admission metadata, isolated from analytics and retrieved knowledge."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.db.schema import metadata

demo_policy = Table(
    "demo_policy",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("fingerprint", String(64), nullable=False),
    CheckConstraint("id = 1", name="demo_policy_singleton"),
    schema="operations",
)
demo_months = Table(
    "demo_months",
    metadata,
    Column("month", Date, primary_key=True),
    Column("legacy_reserved_micro_usd", BigInteger, nullable=False, server_default="0"),
    Column("unknown_requests", Integer, nullable=False, server_default="0"),
    Column("charged_micro_usd", BigInteger, nullable=False),
    Column("rate_minute", DateTime(timezone=True), nullable=False),
    Column("rate_count", Integer, nullable=False),
    CheckConstraint("charged_micro_usd >= 0 AND rate_count >= 0", name="demo_months_nonnegative"),
    CheckConstraint(
        "legacy_reserved_micro_usd >= 0 AND unknown_requests >= 0", name="demo_months_accounting"
    ),
    schema="operations",
)
demo_leases = Table(
    "demo_leases",
    metadata,
    Column("request_id", String(32), primary_key=True),
    Column("admitted_at", DateTime(timezone=True), nullable=False),
    Column("month", Date, ForeignKey("operations.demo_months.month"), nullable=False),
    schema="operations",
)

access_tokens = Table(
    "access_tokens",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("secret_digest", String(64), nullable=False),
    Column("name", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("max_requests", Integer, nullable=False),
    Column("budget_micro_usd", BigInteger, nullable=False),
    Column("requests_per_minute", Integer, nullable=False),
    CheckConstraint(
        "max_requests BETWEEN 1 AND 10000 AND budget_micro_usd BETWEEN 0 AND 100000000 "
        "AND requests_per_minute BETWEEN 1 AND 60",
        name="access_tokens_limits",
    ),
    CheckConstraint("expires_at > created_at", name="access_tokens_expiry"),
    schema="operations",
)
access_usage = Table(
    "access_usage",
    metadata,
    Column("token_id", String(32), ForeignKey("operations.access_tokens.id"), primary_key=True),
    Column("admitted_requests", Integer, nullable=False),
    Column("reserved_micro_usd", BigInteger, nullable=False),
    Column("charged_micro_usd", BigInteger, nullable=False, server_default="0"),
    Column("unknown_requests", Integer, nullable=False, server_default="0"),
    Column("rate_minute", DateTime(timezone=True)),
    Column("rate_count", Integer, nullable=False),
    Column("first_used_at", DateTime(timezone=True)),
    Column("last_used_at", DateTime(timezone=True)),
    CheckConstraint(
        "admitted_requests >= 0 AND reserved_micro_usd >= 0 AND rate_count >= 0",
        name="access_usage_nonnegative",
    ),
    CheckConstraint(
        "charged_micro_usd >= 0 AND unknown_requests >= 0", name="access_usage_accounting"
    ),
    schema="operations",
)
access_sessions = Table(
    "access_sessions",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "token_id",
        String(32),
        ForeignKey("operations.access_tokens.id"),
        nullable=False,
        index=True,
    ),
    Column("secret_digest", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("expires_at > created_at", name="access_sessions_expiry"),
    schema="operations",
)
access_requests = Table(
    "access_requests",
    metadata,
    Column("request_id", String(32), primary_key=True),
    Column(
        "token_id",
        String(32),
        ForeignKey("operations.access_tokens.id"),
        nullable=False,
        index=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("reserved_micro_usd", BigInteger, nullable=False),
    Column("charged_micro_usd", BigInteger),
    Column("usage_state", String(20), nullable=False, server_default="not_admitted"),
    Column("pricing_version", String(64)),
    Column("summary", JSONB, nullable=False),
    CheckConstraint("reserved_micro_usd >= 0", name="access_requests_nonnegative"),
    CheckConstraint(
        "(usage_state='recorded' AND charged_micro_usd IS NOT NULL AND charged_micro_usd>=0) OR "
        "(usage_state IN ('not_admitted','pending','unknown','legacy') "
        "AND charged_micro_usd IS NULL)",
        name="access_requests_accounting",
    ),
    schema="operations",
)
