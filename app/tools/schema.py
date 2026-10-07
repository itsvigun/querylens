"""Expose the reviewed analytics schema, without database credentials/catalog data."""

from sqlalchemy.dialects import postgresql

from app.db.schema import ANALYTICS_TABLES
from app.demo import DATASET_VERSION, REFERENCE_DATE


def get_database_schema() -> dict:
    return {
        "status": "ok",
        "dialect": "postgres",
        "dataset_version": DATASET_VERSION,
        "reference_date": REFERENCE_DATE.isoformat(),
        "timezone": "UTC",
        "currency": "EUR",
        "tables": [
            {
                "schema": "analytics",
                "name": table.name,
                "columns": [
                    {
                        "name": column.name,
                        "type": column.type.compile(dialect=postgresql.dialect()),
                        "nullable": column.nullable,
                        "primary_key": column.primary_key,
                        "references": sorted(key.target_fullname for key in column.foreign_keys),
                    }
                    for column in table.columns
                ],
                "constraints": sorted(
                    str(constraint.sqltext)
                    for constraint in table.constraints
                    if hasattr(constraint, "sqltext")
                ),
            }
            for table in ANALYTICS_TABLES
        ],
        "limitations": [
            "Reviewed schema metadata only; schema drift must be checked with Alembic.",
            "Only the listed analytics tables are allowed. Knowledge and catalogs are excluded.",
            "Relative periods use the demo reference date; business definitions are in knowledge/.",
        ],
    }
