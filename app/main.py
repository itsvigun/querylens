from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import BoundedSemaphore
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.access import AccessStore
from app.api.access import authenticate_request
from app.api.access import router as access_router
from app.api.body_limit import ChatBodyLimitMiddleware
from app.api.chat import router as chat_router
from app.api.demo import router as demo_router
from app.api.health import router as health_router
from app.api.ui import UI_DIRECTORY
from app.api.ui import router as ui_router
from app.config import (
    AccessSettings,
    DemoControlSettings,
    EmbeddingSettings,
    LLMSettings,
    PublicDemoSettings,
    Settings,
)
from app.db.connection import create_database_engine, migration_heads
from app.demo_gate import AdmissionError, DemoGate, DemoPolicy
from app.observability import REQUEST_ID, log_access, log_request


def create_app(
    settings: Settings | None = None,
    *,
    demo_settings: PublicDemoSettings | None = None,
    access_settings: AccessSettings | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        demo = demo_settings if demo_settings is not None else PublicDemoSettings()
        access = access_settings if access_settings is not None else AccessSettings()
        if access.required and not demo.public_demo_enabled:
            raise ValueError("Invitation access requires shared public controls")
        runtime = (
            settings
            if settings is not None
            else (DemoControlSettings() if demo.public_demo_enabled else Settings())
        )
        application.state.engine = create_database_engine(runtime)
        application.state.demo_gate = None
        application.state.demo_engine = None
        if demo.public_demo_enabled:
            application.state.llm_settings = LLMSettings()
            application.state.embedding_settings = EmbeddingSettings()
            application.state.demo_engine = create_database_engine(DemoControlSettings())
            application.state.demo_gate = DemoGate(
                application.state.demo_engine,
                DemoPolicy.from_settings(
                    demo, application.state.llm_settings, application.state.embedding_settings
                ),
            )
        application.state.chat_lock = BoundedSemaphore(1)
        application.state.access_settings = access
        application.state.access_store = (
            AccessStore(application.state.demo_engine) if access.required else None
        )
        try:
            application.state.migration_heads = migration_heads()
            yield
        finally:
            application.state.engine.dispose()
            if application.state.demo_engine is not None:
                application.state.demo_engine.dispose()

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
    application.include_router(access_router)
    application.include_router(ui_router)
    application.mount("/assets", StaticFiles(directory=UI_DIRECTORY / "assets"), name="assets")
    application.add_middleware(ChatBodyLimitMiddleware)

    @application.middleware("http")
    async def observe_chat(request, call_next):
        path = request.url.path
        chat_boundary = path == "/api/chat" and request.method == "POST"
        public = path in {
            "/",
            "/health/live",
            "/health/ready",
            "/api/access/login",
            "/api/access/logout",
        } or path.startswith("/assets/")
        protected = request.app.state.access_settings.required and not public
        if not chat_boundary and not protected and not path.startswith("/api/access/"):
            return await call_next(request)
        request_id = uuid4().hex
        token = REQUEST_ID.set(request_id)
        started = monotonic()
        try:
            try:
                if protected:
                    await run_in_threadpool(authenticate_request, request)
                response = await call_next(request)
            except AdmissionError as error:
                result = {
                    "status": "error",
                    "error": {"category": error.category},
                    "request_id": request_id,
                }
                request.state.chat_result = result
                response = JSONResponse(status_code=error.status_code, content=result)
                if error.status_code == 401:
                    response.headers["WWW-Authenticate"] = "Bearer"
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
                        413: "request_too_large",
                    }.get(response.status_code, "request_failed")
                },
            }
            result = getattr(request.state, "chat_result", fallback)
            identity = getattr(request.state, "access_identity", None)
            duration_ms = int((monotonic() - started) * 1000)
            if chat_boundary:
                recorded = None
                if identity is not None:
                    recorded = await run_in_threadpool(
                        request.app.state.access_store.audit,
                        identity,
                        request_id,
                        result,
                        duration_ms,
                        response.status_code,
                    )
                log_request(
                    request_id,
                    result,
                    duration_ms,
                    http_status=response.status_code,
                    token_id=identity.token_id if identity else None,
                    audit_recorded=recorded,
                )
            elif path in {"/api/access/login", "/api/access/logout"} or response.status_code >= 400:
                category = (result.get("error") or {}).get("category")
                if response.status_code < 400:
                    category = "access_login" if path.endswith("/login") else "access_logout"
                log_access(
                    request_id,
                    category,
                    response.status_code,
                    identity.token_id if identity else None,
                )
            response.headers["X-Request-ID"] = request_id
            response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            REQUEST_ID.reset(token)

    @application.exception_handler(AdmissionError)
    async def access_failure(request, error):
        result = {
            "status": "error",
            "error": {"category": error.category},
            "request_id": REQUEST_ID.get(),
        }
        request.state.chat_result = result
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after is not None else {}
        if error.status_code == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(status_code=error.status_code, content=result, headers=headers)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Validation errors may include arbitrary submitted fields, including secrets.
        return JSONResponse(status_code=422, content={"detail": "Invalid request body."})

    return application


app = create_app()
