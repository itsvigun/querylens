from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.demo import router as demo_router
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
        description=(
            "Synthetic analytics foundation with validated SQL and documentation retrieval tools."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    application.include_router(demo_router)
    return application


app = create_app()
