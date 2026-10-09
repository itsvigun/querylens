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
    Column("charged_micro_usd", BigInteger, nullable=False),
    Column("rate_minute", DateTime(timezone=True), nullable=False),
    Column("rate_count", Integer, nullable=False),
    CheckConstraint("charged_micro_usd >= 0 AND rate_count >= 0", name="demo_months_nonnegative"),
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
