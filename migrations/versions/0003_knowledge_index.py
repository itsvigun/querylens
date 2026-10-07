"""Create versioned knowledge indexes and source-addressable vector chunks."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0003_knowledge_index"
down_revision = "0002_analytics_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "indexes",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("index_version", sa.String(32), nullable=False),
        sa.Column("chunker_version", sa.String(64), nullable=False),
        sa.Column("corpus_hash", sa.String(64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("dimensions BETWEEN 1 AND 3072", name="indexes_dimensions"),
        sa.CheckConstraint("chunk_count BETWEEN 1 AND 512", name="indexes_chunk_count"),
        sa.UniqueConstraint("name", "dimensions", name="indexes_name_dimensions"),
        schema="knowledge",
    )
    op.create_table(
        "chunks",
        sa.Column("index_name", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_path", sa.String(256), nullable=False),
        sa.Column("heading", sa.String(256), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=False),
        sa.Column("document_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.ForeignKeyConstraint(
            ["index_name", "dimensions"],
            ["knowledge.indexes.name", "knowledge.indexes.dimensions"],
            name="chunks_index_dimensions",
        ),
        sa.CheckConstraint(
            "public.vector_dims(embedding) = dimensions", name="chunks_vector_dimensions"
        ),
        sa.CheckConstraint("public.vector_norm(embedding) > 0", name="chunks_nonzero_vector"),
        sa.CheckConstraint(
            "ordinal >= 0 AND line_start > 0 AND line_end >= line_start", name="chunks_position"
        ),
        sa.CheckConstraint("octet_length(content) BETWEEN 1 AND 2000", name="chunks_content_bytes"),
        schema="knowledge",
    )


def downgrade():
    op.drop_table("chunks", schema="knowledge")
    op.drop_table("indexes", schema="knowledge")
