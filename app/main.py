from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import BoundedSemaphore
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.demo import router as demo_router
from app.api.health import router as health_router
from app.api.ui import UI_DIRECTORY
from app.api.ui import router as ui_router
from app.config import Settings
from app.db.connection import create_database_engine, migration_heads
from app.observability import REQUEST_ID, log_request


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
    application.include_router(ui_router)
    application.mount("/assets", StaticFiles(directory=UI_DIRECTORY / "assets"), name="assets")

    @application.middleware("http")
    async def observe_chat(request, call_next):
        if request.url.path != "/api/chat" or request.method != "POST":
            return await call_next(request)
        request_id = uuid4().hex
        token = REQUEST_ID.set(request_id)
        started = monotonic()
        try:
            try:
                response = await call_next(request)
            except Exception:
                response = JSONResponse(
                    status_code=500,
                    content={"status": "error", "error": {"category": "request_failed"}},
                )
            fallback = {
                "status": "error",
                "error": {
                    "category": {
                        422: "invalid_request",
                        429: "busy",
                    }.get(response.status_code, "request_failed")
                },
            }
            log_request(
                request_id,
                getattr(request.state, "chat_result", fallback),
                int((monotonic() - started) * 1000),
                http_status=response.status_code,
            )
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            REQUEST_ID.reset(token)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Validation errors may include arbitrary submitted fields, including secrets.
        return JSONResponse(status_code=422, content={"detail": "Invalid request body."})

    return application


app = create_app()
