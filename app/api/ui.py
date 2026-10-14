"""Serve the local demo UI without database or provider calls."""

from hashlib import sha256
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

UI_DIRECTORY = Path(__file__).resolve().parents[1] / "static"
router = APIRouter()


@router.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    page = (UI_DIRECTORY / "index.html").read_text(encoding="utf-8")
    for asset in ("app.css", "app.js"):
        version = sha256((UI_DIRECTORY / "assets" / asset).read_bytes()).hexdigest()[:16]
        page = page.replace(f'"/assets/{asset}"', f'"/assets/{asset}?v={version}"')
    return HTMLResponse(
        page,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self'; base-uri 'none'; "
                "form-action 'self'; frame-ancestors 'none'"
            ),
        },
    )
