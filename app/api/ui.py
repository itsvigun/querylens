"""Serve the local demo UI without database or provider calls."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

UI_DIRECTORY = Path(__file__).resolve().parents[1] / "static"
router = APIRouter()


@router.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(
        UI_DIRECTORY / "index.html",
        media_type="text/html",
        headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self'; base-uri 'none'; "
                "form-action 'self'; frame-ancestors 'none'"
            ),
        },
    )
