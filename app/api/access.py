"""Invitation entry and logout; administration is intentionally CLI-only."""

import hmac

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import Field, SecretStr

from app.access import csrf_value
from app.demo_gate import AdmissionError
from app.llm.contracts import StrictModel

router = APIRouter(prefix="/api/access", tags=["access"])
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="InvitationToken")


class AccessLogin(StrictModel):
    token: SecretStr = Field(min_length=80, max_length=80)


def browser_origin(request: Request):
    settings = request.app.state.access_settings
    if (
        request.headers.get("origin") != settings.access_public_origin
        or request.headers.get("x-querylens-client") != "browser"
        or request.headers.get("sec-fetch-site") not in {None, "same-origin"}
    ):
        raise AdmissionError("access_origin_denied", 403)


def browser_csrf(request: Request):
    browser_origin(request)
    session = request.cookies.get(request.app.state.access_settings.cookie_name, "")
    supplied = request.headers.get("x-csrf-token", "")
    if (
        not session
        or len(supplied) != 64
        or not hmac.compare_digest(supplied.encode(), csrf_value(session).encode())
    ):
        raise AdmissionError("access_origin_denied", 403)


def authenticate_request(request: Request):
    store = request.app.state.access_store
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() != "bearer":
            raise AdmissionError("access_denied", 401)
        identity = store.authenticate(credential)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if (
                origin is not None
                and origin != request.app.state.access_settings.access_public_origin
            ):
                raise AdmissionError("access_origin_denied", 403)
    else:
        credential = request.cookies.get(request.app.state.access_settings.cookie_name)
        if credential is None:
            raise AdmissionError("access_required", 401)
        identity = store.authenticate(credential, session=True)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            browser_csrf(request)
    request.state.access_identity = identity
    return identity


@router.get("/status")
def access_status(request: Request):
    if request.app.state.access_store is None:
        return {"required": False, "authenticated": True}
    result = request.app.state.access_store.status(
        request.state.access_identity, request.app.state.demo_gate.policy
    )
    session = request.cookies.get(request.app.state.access_settings.cookie_name)
    result["csrf_token"] = (
        csrf_value(session) if request.state.access_identity.session_id is not None else None
    )
    return result


@router.post("/login")
def access_login(body: AccessLogin, request: Request):
    store = request.app.state.access_store
    if store is None:
        raise AdmissionError("access_disabled", 403)
    browser_origin(request)
    session, age, identity = store.create_session(
        body.token.get_secret_value(), request.app.state.access_settings.access_session_ttl_seconds
    )
    request.state.access_identity = identity
    response = JSONResponse({"authenticated": True, "csrf_token": csrf_value(session)})
    response.set_cookie(
        request.app.state.access_settings.cookie_name,
        session,
        max_age=age,
        secure=request.app.state.access_settings.access_cookie_secure,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return response


@router.post("/logout")
def access_logout(request: Request):
    browser_csrf(request)
    session = request.cookies.get(request.app.state.access_settings.cookie_name)
    if request.app.state.access_store is not None and session:
        request.app.state.access_store.logout(session)
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(
        request.app.state.access_settings.cookie_name,
        secure=request.app.state.access_settings.access_cookie_secure,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return response
