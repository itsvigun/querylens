from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import BoundedSemaphore

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.api.demo import router as demo_router
from app.api.health import router as health_router
from app.config import Settings
from app.db.connection import create_database_engine, migration_heads


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.engine = create_database_engine(settings or Settings())
        application.state.chat_lock = BoundedSemaphore(1)
        try:
            application.state.migration_heads = migration_heads()
            yield
        finally:
            application.state.engine.dispose()

    application = FastAPI(
        title="QueryLens",
        description=(
            "Synthetic analytics with documentation retrieval and bounded OpenAI tool calling."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    application.include_router(demo_router)
    application.include_router(chat_router)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Validation errors may include arbitrary submitted fields, including secrets.
        return JSONResponse(status_code=422, content={"detail": "Invalid request body."})

    return application


app = create_app()
