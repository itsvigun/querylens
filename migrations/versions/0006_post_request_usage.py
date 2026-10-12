"""Replace monetary reservations with post-request usage estimates; archive old charges."""

import sqlalchemy as sa
from alembic import op

revision = "0006_post_request_usage"
down_revision = "0005_invitation_access"
branch_labels = None
depends_on = None


def require_drained():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM operations.demo_leases")):
        raise RuntimeError("Stop/drain API workers and recover stale leases before migrating")


def upgrade():
    require_drained()
    for table in ("demo_months", "access_usage"):
        op.add_column(
            table,
            sa.Column("unknown_requests", sa.Integer(), nullable=False, server_default="0"),
            schema="operations",
        )
    op.add_column(
        "demo_months",
        sa.Column("legacy_reserved_micro_usd", sa.BigInteger(), nullable=False, server_default="0"),
        schema="operations",
    )
    # These old amounts are reservations, not measured usage. Preserve them as history.
    op.execute(
        "UPDATE operations.demo_months SET "
        "legacy_reserved_micro_usd=charged_micro_usd, charged_micro_usd=0"
    )
    op.create_check_constraint(
        "demo_months_accounting",
        "demo_months",
        "legacy_reserved_micro_usd >= 0 AND unknown_requests >= 0",
        schema="operations",
    )
    op.add_column(
        "access_usage",
        sa.Column("charged_micro_usd", sa.BigInteger(), nullable=False, server_default="0"),
        schema="operations",
    )
    op.create_check_constraint(
        "access_usage_accounting",
        "access_usage",
        "charged_micro_usd >= 0 AND unknown_requests >= 0",
        schema="operations",
    )
    op.add_column(
        "access_requests", sa.Column("charged_micro_usd", sa.BigInteger()), schema="operations"
    )
    op.add_column(
        "access_requests",
        sa.Column("usage_state", sa.String(20), nullable=False, server_default="not_admitted"),
        schema="operations",
    )
    op.execute(
        "UPDATE operations.access_requests SET usage_state='legacy' WHERE reserved_micro_usd>0"
    )
    op.create_check_constraint(
        "access_requests_accounting",
        "access_requests",
        "(usage_state='recorded' AND charged_micro_usd IS NOT NULL AND charged_micro_usd>=0) OR "
        "(usage_state IN ('not_admitted','pending','unknown','legacy') "
        "AND charged_micro_usd IS NULL)",
        schema="operations",
    )


def downgrade():
    require_drained()
    # Preserve known usage alongside archived reservations when restoring the older ledger.
    op.execute(
        "UPDATE operations.demo_months SET "
        "charged_micro_usd=charged_micro_usd+legacy_reserved_micro_usd"
    )
    op.execute(
        "UPDATE operations.access_usage SET reserved_micro_usd=reserved_micro_usd+charged_micro_usd"
    )
    op.execute(
        "UPDATE operations.access_requests SET "
        "reserved_micro_usd=reserved_micro_usd+COALESCE(charged_micro_usd,0)"
    )
    for table in ("access_requests", "access_usage", "demo_months"):
        op.drop_constraint(table + "_accounting", table, schema="operations")
    op.drop_column("access_requests", "usage_state", schema="operations")
    op.drop_column("access_requests", "charged_micro_usd", schema="operations")
    op.drop_column("access_usage", "charged_micro_usd", schema="operations")
    op.drop_column("demo_months", "legacy_reserved_micro_usd", schema="operations")
    for table in ("access_usage", "demo_months"):
        op.drop_column(table, "unknown_requests", schema="operations")
