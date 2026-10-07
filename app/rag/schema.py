"""Knowledge metadata shares the migration metadata, never the analytics allowlist."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from app.db.schema import metadata

indexes = Table(
    "indexes",
    metadata,
    Column("name", String(64), primary_key=True),
    Column("provider", String(32), nullable=False),
    Column("model", String(128), nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("index_version", String(32), nullable=False),
    Column("chunker_version", String(64), nullable=False),
    Column("corpus_hash", String(64), nullable=False),
    Column("chunk_count", Integer, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("dimensions BETWEEN 1 AND 3072", name="indexes_dimensions"),
    CheckConstraint("chunk_count BETWEEN 1 AND 512", name="indexes_chunk_count"),
    UniqueConstraint("name", "dimensions", name="indexes_name_dimensions"),
    schema="knowledge",
)

chunks = Table(
    "chunks",
    metadata,
    Column("index_name", String(64), primary_key=True),
    Column("id", String(64), primary_key=True),
    Column("source_path", String(256), nullable=False),
    Column("heading", String(256), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("line_start", Integer, nullable=False),
    Column("line_end", Integer, nullable=False),
    Column("document_hash", String(64), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("content", Text, nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("embedding", Vector(), nullable=False),
    ForeignKeyConstraint(
        ["index_name", "dimensions"],
        ["knowledge.indexes.name", "knowledge.indexes.dimensions"],
        name="chunks_index_dimensions",
    ),
    CheckConstraint("public.vector_dims(embedding) = dimensions", name="chunks_vector_dimensions"),
    CheckConstraint("public.vector_norm(embedding) > 0", name="chunks_nonzero_vector"),
    CheckConstraint(
        "ordinal >= 0 AND line_start > 0 AND line_end >= line_start", name="chunks_position"
    ),
    CheckConstraint("octet_length(content) BETWEEN 1 AND 2000", name="chunks_content_bytes"),
    schema="knowledge",
)
