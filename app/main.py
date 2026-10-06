from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import Settings
from app.db.connection import create_database_engine, migration_heads


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.engine = create_database_engine(settings or Settings())
        try:
            application.state.migration_heads = migration_heads()
            yield
        finally:
            application.state.engine.dispose()

    application = FastAPI(
        title="QueryLens",
        description="Business analytics over synthetic PostgreSQL data. Stage 0: health API.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    return application


app = create_app()
