"""Create analytics tables and an isolated knowledge schema.

Revision ID: 0002_analytics_schema
Revises: 0001_enable_pgvector
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_analytics_schema"
down_revision = "0001_enable_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA analytics")
    op.execute("CREATE SCHEMA knowledge")
    op.execute("REVOKE ALL ON SCHEMA analytics, knowledge FROM PUBLIC")
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.CheckConstraint("id > 0", name="users_positive_id"),
        sa.CheckConstraint("country IN ('DE', 'PL', 'FR', 'ES')", name="users_country"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="users_status"),
        schema="analytics",
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("analytics.users.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.CheckConstraint("id > 0", name="orders_positive_id"),
        sa.CheckConstraint("amount >= 0", name="orders_nonnegative_amount"),
        sa.CheckConstraint("currency = 'EUR'", name="orders_currency"),
        sa.CheckConstraint(
            "status IN ('completed', 'refunded', 'cancelled')", name="orders_status"
        ),
        schema="analytics",
    )
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("analytics.users.id"), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id > 0", name="events_positive_id"),
        sa.CheckConstraint("event_type IN ('session', 'checkout')", name="events_type"),
        schema="analytics",
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("analytics.users.id"), nullable=False),
        sa.Column("plan", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("id > 0", name="subscriptions_positive_id"),
        sa.CheckConstraint("plan IN ('basic', 'pro', 'enterprise')", name="subscriptions_plan"),
        sa.CheckConstraint(
            "cancelled_at IS NULL OR cancelled_at >= started_at", name="subscriptions_dates"
        ),
        schema="analytics",
    )
    for table, name, columns in (
        ("users", "ix_users_registered_at", ["registered_at"]),
        ("users", "ix_users_country_registered_at", ["country", "registered_at"]),
        ("orders", "ix_orders_status_created_at", ["status", "created_at"]),
        ("orders", "ix_orders_user_created_at", ["user_id", "created_at"]),
        ("events", "ix_events_type_created_at", ["event_type", "created_at"]),
        ("events", "ix_events_user_created_at", ["user_id", "created_at"]),
        ("subscriptions", "ix_subscriptions_plan_started_at", ["plan", "started_at"]),
        ("subscriptions", "ix_subscriptions_cancelled_at", ["cancelled_at"]),
        ("subscriptions", "ix_subscriptions_user_id", ["user_id"]),
    ):
        op.create_index(name, table, columns, schema="analytics")


def downgrade() -> None:
    for table in ("subscriptions", "events", "orders", "users"):
        op.drop_table(table, schema="analytics")
    # No CASCADE: refuse to discard any later knowledge objects silently.
    op.execute("DROP SCHEMA knowledge")
    op.execute("DROP SCHEMA analytics")
