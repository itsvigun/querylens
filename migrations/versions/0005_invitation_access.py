"""Named invitation tokens, browser sessions and durable usage metadata."""

from alembic import op

revision = "0005_invitation_access"
down_revision = "0004_demo_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE operations.access_tokens (
	id VARCHAR(32) NOT NULL,
	secret_digest VARCHAR(64) NOT NULL,
	name VARCHAR(128) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	max_requests INTEGER NOT NULL,
	budget_micro_usd BIGINT NOT NULL,
	requests_per_minute INTEGER NOT NULL,
	PRIMARY KEY (id),
        CONSTRAINT access_tokens_limits CHECK (max_requests BETWEEN 1 AND 10000 AND
budget_micro_usd BETWEEN 0 AND 100000000 AND requests_per_minute BETWEEN 1 AND 60),
	CONSTRAINT access_tokens_expiry CHECK (expires_at > created_at)
)
""")
    op.execute("""
CREATE TABLE operations.access_usage (
	token_id VARCHAR(32) NOT NULL,
	admitted_requests INTEGER NOT NULL,
	reserved_micro_usd BIGINT NOT NULL,
	rate_minute TIMESTAMP WITH TIME ZONE,
	rate_count INTEGER NOT NULL,
	first_used_at TIMESTAMP WITH TIME ZONE,
	last_used_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (token_id),
        CONSTRAINT access_usage_nonnegative CHECK (admitted_requests >= 0 AND reserved_micro_usd
>= 0 AND rate_count >= 0),
	FOREIGN KEY(token_id) REFERENCES operations.access_tokens (id)
)
""")
    op.execute("""
CREATE TABLE operations.access_sessions (
	id VARCHAR(32) NOT NULL,
	token_id VARCHAR(32) NOT NULL,
	secret_digest VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT access_sessions_expiry CHECK (expires_at > created_at),
	FOREIGN KEY(token_id) REFERENCES operations.access_tokens (id)
)
""")
    op.execute(
        "CREATE INDEX ix_operations_access_sessions_token_id "
        "ON operations.access_sessions (token_id)"
    )
    op.execute("""
CREATE TABLE operations.access_requests (
	request_id VARCHAR(32) NOT NULL,
	token_id VARCHAR(32) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	reserved_micro_usd BIGINT NOT NULL,
	pricing_version VARCHAR(64),
	summary JSONB NOT NULL,
	PRIMARY KEY (request_id),
	CONSTRAINT access_requests_nonnegative CHECK (reserved_micro_usd >= 0),
	FOREIGN KEY(token_id) REFERENCES operations.access_tokens (id)
)
""")
    op.execute(
        "CREATE INDEX ix_operations_access_requests_token_id "
        "ON operations.access_requests (token_id)"
    )


def downgrade():
    op.drop_table("access_requests", schema="operations")
    op.drop_table("access_sessions", schema="operations")
    op.drop_table("access_usage", schema="operations")
    op.drop_table("access_tokens", schema="operations")
