"""SQLAlchemy Core metadata for the synthetic analytics dataset."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    String,
    Table,
)

metadata = MetaData(schema="analytics")

users = Table(
    "users",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("country", String(2), nullable=False),
    Column("registered_at", DateTime(timezone=True), nullable=False),
    Column("status", String(16), nullable=False),
    CheckConstraint("id > 0", name="users_positive_id"),
    CheckConstraint("country IN ('DE', 'PL', 'FR', 'ES')", name="users_country"),
    CheckConstraint("status IN ('active', 'disabled')", name="users_status"),
    Index("ix_users_registered_at", "registered_at"),
    Index("ix_users_country_registered_at", "country", "registered_at"),
)

orders = Table(
    "orders",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("user_id", BigInteger, ForeignKey("analytics.users.id"), nullable=False),
    Column("amount", Numeric(12, 2), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("status", String(16), nullable=False),
    CheckConstraint("id > 0", name="orders_positive_id"),
    CheckConstraint("amount >= 0", name="orders_nonnegative_amount"),
    CheckConstraint("currency = 'EUR'", name="orders_currency"),
    CheckConstraint("status IN ('completed', 'refunded', 'cancelled')", name="orders_status"),
    Index("ix_orders_status_created_at", "status", "created_at"),
    Index("ix_orders_user_created_at", "user_id", "created_at"),
)

events = Table(
    "events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("user_id", BigInteger, ForeignKey("analytics.users.id"), nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("id > 0", name="events_positive_id"),
    CheckConstraint("event_type IN ('session', 'checkout')", name="events_type"),
    Index("ix_events_type_created_at", "event_type", "created_at"),
    Index("ix_events_user_created_at", "user_id", "created_at"),
)

subscriptions = Table(
    "subscriptions",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("user_id", BigInteger, ForeignKey("analytics.users.id"), nullable=False),
    Column("plan", String(16), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("cancelled_at", DateTime(timezone=True)),
    CheckConstraint("id > 0", name="subscriptions_positive_id"),
    CheckConstraint("plan IN ('basic', 'pro', 'enterprise')", name="subscriptions_plan"),
    CheckConstraint(
        "cancelled_at IS NULL OR cancelled_at >= started_at", name="subscriptions_dates"
    ),
    Index("ix_subscriptions_plan_started_at", "plan", "started_at"),
    Index("ix_subscriptions_cancelled_at", "cancelled_at"),
    Index("ix_subscriptions_user_id", "user_id"),
)

ANALYTICS_TABLES = (users, orders, events, subscriptions)
