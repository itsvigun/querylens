"""Persist shared public demo admission reservations and active leases."""

import sqlalchemy as sa
from alembic import op

revision = "0004_demo_controls"
down_revision = "0003_knowledge_index"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA operations")
    op.create_table(
        "demo_policy",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.CheckConstraint("id = 1", name="demo_policy_singleton"),
        schema="operations",
    )
    op.create_table(
        "demo_months",
        sa.Column("month", sa.Date, primary_key=True),
        sa.Column("charged_micro_usd", sa.BigInteger, nullable=False),
        sa.Column("rate_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rate_count", sa.Integer, nullable=False),
        sa.CheckConstraint(
            "charged_micro_usd >= 0 AND rate_count >= 0", name="demo_months_nonnegative"
        ),
        schema="operations",
    )
    op.create_table(
        "demo_leases",
        sa.Column("request_id", sa.String(32), primary_key=True),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("month", sa.Date, sa.ForeignKey("operations.demo_months.month"), nullable=False),
        schema="operations",
    )


def downgrade():
    op.drop_table("demo_leases", schema="operations")
    op.drop_table("demo_months", schema="operations")
    op.drop_table("demo_policy", schema="operations")
    op.execute("DROP SCHEMA operations")
