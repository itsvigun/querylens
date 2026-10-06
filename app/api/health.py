import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.db.connection import database_checks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", responses={503: {"description": "Database dependencies are not ready"}})
def ready(request: Request) -> JSONResponse:
    try:
        checks = database_checks(request.app.state.engine, request.app.state.migration_heads)
    except (SQLAlchemyError, OSError):
        # Do not log exception text or return connection details to the caller.
        logger.warning("Database readiness check failed")
        checks = {"database": False, "migrations": False, "pgvector": False}

    is_ready = all(checks.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"status": "ready" if is_ready else "not_ready", "checks": checks},
    )
