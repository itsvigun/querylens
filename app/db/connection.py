from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text

from app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_database_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        connect_args=settings.database_connect_args,
        pool_size=5,
        max_overflow=0,
        pool_timeout=settings.db_connect_timeout_seconds,
        pool_pre_ping=True,
        hide_parameters=True,
    )


def migration_heads() -> set[str]:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    return set(ScriptDirectory.from_config(config).get_heads())


def database_checks(engine: Engine, expected_heads: set[str]) -> dict[str, bool]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        current_heads = set(MigrationContext.configure(connection).get_current_heads())
        pgvector_installed = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
        return {
            "database": True,
            "migrations": current_heads == expected_heads,
            "pgvector": bool(pgvector_installed),
        }
