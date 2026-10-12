"""Offline access contracts and no-provider denials; DB safety has separate tests."""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.access import AccessIdentity, credential_parts, csrf_value, issue_credential
from app.config import AccessSettings, PublicDemoSettings
from app.demo_gate import AdmissionError
from app.main import create_app
from app.observability import LOGGER
from scripts.access_tokens import TokenOptions
from tests.test_demo_gate import policy

ORIGIN = "https://querylens.test"
BROWSER = {"Origin": ORIGIN, "X-QueryLens-Client": "browser"}


class OfflineStore:
    def __init__(self):
        self.token_id, self.token, _ = issue_credential("qlt")
        self.sessions = {}
        self.revoked = False
        self.audits = []

    def authenticate(self, credential, *, session=False):
        if self.revoked:
            raise AdmissionError("access_denied", 401)
        if session and credential in self.sessions:
            return AccessIdentity(self.token_id, self.sessions[credential])
        if not session and credential == self.token:
            return AccessIdentity(self.token_id)
        raise AdmissionError("access_denied", 401)

    def create_session(self, credential, ttl):
        self.authenticate(credential)
        sid, session, _ = issue_credential("qls")
        self.sessions[session] = sid
        return session, ttl, AccessIdentity(self.token_id, sid)

    def status(self, identity, policy):
        return {
            "required": True,
            "authenticated": True,
            "name": "Offline company",
            "remaining_requests": 5,
            "expires_at": "2027-01-01T00:00:00+00:00",
        }

    def logout(self, credential):
        self.sessions.pop(credential, None)

    def audit(self, *values):
        self.audits.append(values)
        return True


class OfflineGate:
    policy = policy(public_chat_monthly_budget_usd="1")

    def __init__(self):
        self.events = []
        self.error = None

    def admit(self, request_id, *, identity):
        self.events.append(("admit", request_id, identity.token_id))
        if self.error:
            raise AdmissionError(self.error, 429)

    def release(self, request_id):
        self.events.append(("release", request_id))


@pytest.fixture
def access_client(settings, monkeypatch):
    monkeypatch.setenv("DEMO_CONTROL_PASSWORD", "offline-control-password")
    calls, logs = [], []
    monkeypatch.setattr(
        "app.api.chat.ask",
        lambda *a, **k: (
            calls.append(a)
            or {
                "status": "answered",
                "explanation": "offline secret marker",
                "usage": {"requests": 1, "model": "gpt-5.4-mini"},
            }
        ),
    )

    class Capture(logging.Handler):
        def emit(self, record):
            logs.append(json.loads(record.getMessage()))

    handler = Capture()
    LOGGER.addHandler(handler)
    app = create_app(
        settings,
        demo_settings=PublicDemoSettings(_env_file=None, public_demo_enabled=True),
        access_settings=AccessSettings(
            _env_file=None, token_access_required=True, access_public_origin=ORIGIN
        ),
    )
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            store, gate = OfflineStore(), OfflineGate()
            app.state.access_store = store
            app.state.demo_gate = gate
            yield client, store, gate, calls, logs
    finally:
        LOGGER.removeHandler(handler)


def test_railway_defaults_to_invitation_access_and_exact_https_origin():
    settings = AccessSettings(
        _env_file=None, railway_environment_id="hosted", railway_public_domain="demo.test"
    )
    assert settings.required and settings.access_public_origin == "https://demo.test"
    assert settings.cookie_name.startswith("__Host-")
    for values in (
        {"token_access_required": False},
        {"access_cookie_secure": False},
        {"access_public_origin": "http://demo.test"},
        {"access_public_origin": "https://demo.test/"},
        {"access_public_origin": "https://user:password@demo.test"},
    ):
        with pytest.raises(ValidationError):
            AccessSettings(
                _env_file=None,
                railway_environment_id="hosted",
                railway_public_domain="demo.test",
                **values,
            )


@pytest.mark.parametrize("value", ["", "123", "Bearer forged", "qlt_" + "a" * 200])
def test_malformed_credentials_fail_with_fixed_error(value):
    with pytest.raises(AdmissionError, match="access_denied"):
        credential_parts(value, "qlt")


def test_credentials_have_independent_random_secrets_and_typed_ids():
    tid, token, digest = issue_credential("qlt")
    assert len(token) == 80 and len(digest) == 64
    assert credential_parts(token, "qlt") == (tid, digest)
    assert token != issue_credential("qlt")[1]
    with pytest.raises(AdmissionError):
        credential_parts(token, "qls")


@pytest.mark.parametrize(
    "options",
    [
        {"name": "\nforged"},
        {"name": " "},
        {"max_requests": 0},
        {"budget_usd": "NaN"},
        {"budget_usd": "0.0000001"},
        {"expires_in_days": 0},
        {"requests_per_minute": 61},
    ],
)
def test_admin_limits_are_bounded(options):
    with pytest.raises(ValidationError):
        TokenOptions(**{"name": "Company", **options})


def test_anonymous_access_is_denied_before_validation_or_provider(access_client):
    client, store, gate, calls, logs = access_client
    for path in ("/api/chat", "/demo", "/docs", "/openapi.json", "/redoc", "/api/access/status"):
        response = (
            client.post(path, content="malformed secret")
            if path == "/api/chat"
            else client.get(path)
        )
        assert response.status_code == 401
        assert response.json()["error"]["category"] == "access_required"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["www-authenticate"] == "Bearer"
    assert client.get("/").status_code == client.get("/assets/app.js").status_code == 200
    assert client.get("/health/live").status_code == 200
    assert not calls and not gate.events and not store.audits
    assert "malformed secret" not in json.dumps(logs)


def test_browser_login_cookie_csrf_status_and_logout(access_client):
    client, store, gate, calls, logs = access_client
    response = client.post("/api/access/login", json={"token": store.token}, headers=BROWSER)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert "Domain=" not in cookie
    session = client.cookies.get("__Host-querylens_session")
    assert session != store.token and store.token not in response.text
    status = client.get("/api/access/status")
    assert status.json()["csrf_token"] == csrf_value(session)
    csrf = status.json()["csrf_token"]
    assert client.get("/docs").status_code == 200
    response = client.post(
        "/api/chat",
        json={"question": "offline question secret"},
        headers={**BROWSER, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200 and len(calls) == 1
    assert gate.events[0][2] == store.token_id
    assert store.audits[0][0].token_id == store.token_id
    summary = next(log for log in logs if log["event"] == "analytics_request")
    assert summary["token_id"] == store.token_id and summary["audit_recorded"] is True
    assert all(
        secret not in json.dumps(logs)
        for secret in (
            store.token,
            session,
            csrf,
            "offline question secret",
            "offline secret marker",
        )
    )
    assert (
        client.post("/api/access/logout", headers={**BROWSER, "X-CSRF-Token": csrf}).status_code
        == 200
    )
    assert client.get("/api/access/status").status_code == 401
    assert not store.sessions


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {**BROWSER},
        {**BROWSER, "X-CSRF-Token": "wrong"},
        {"Origin": "https://evil.test", "X-QueryLens-Client": "browser"},
        {**BROWSER, "Sec-Fetch-Site": "cross-site"},
    ],
)
def test_cookie_requests_require_csrf_and_exact_origin(access_client, headers):
    client, store, gate, calls, _ = access_client
    assert (
        client.post("/api/access/login", json={"token": store.token}, headers=BROWSER).status_code
        == 200
    )
    assert (
        client.post("/api/chat", json={"question": "Revenue?"}, headers=headers).status_code == 403
    )
    assert not calls and not gate.events


def test_bearer_auth_has_no_cookie_dependency_and_rechecks_revocation(access_client):
    client, store, gate, calls, logs = access_client
    headers = {"Authorization": "Bearer " + store.token}
    assert client.get("/api/access/status", headers=headers).status_code == 200
    assert (
        client.post("/api/chat", json={"question": "Revenue?"}, headers=headers).status_code == 200
    )
    assert len(calls) == 1
    store.revoked = True
    assert (
        client.post("/api/chat", json={"question": "Revenue?"}, headers=headers).status_code == 401
    )
    assert len(calls) == 1 and store.token not in json.dumps(logs)


def test_bad_authorization_never_falls_back_to_cookie(access_client):
    client, store, gate, calls, _ = access_client
    client.post("/api/access/login", json={"token": store.token}, headers=BROWSER)
    response = client.get("/api/access/status", headers={"Authorization": "Bearer forged"})
    assert response.status_code == 401 and not calls and not gate.events


def test_login_origin_body_limit_and_validation_do_not_echo_secrets(access_client):
    client, store, gate, calls, logs = access_client
    assert client.post("/api/access/login", json={"token": store.token}).status_code == 403
    response = client.post(
        "/api/access/login", content=b"offline secret marker" * 200, headers=BROWSER
    )
    assert response.status_code == 413
    response = client.post(
        "/api/access/login", json={"token": "private-key", "secret": "private-key"}, headers=BROWSER
    )
    assert response.status_code == 422
    assert "private-key" not in response.text + json.dumps(logs)
    assert not calls and not gate.events and not store.sessions


def test_quota_denials_have_attribution_but_never_invoke_provider(access_client):
    client, store, gate, calls, logs = access_client
    gate.error = "access_request_limit"
    response = client.post(
        "/api/chat",
        json={"question": "Revenue?"},
        headers={"Authorization": "Bearer " + store.token},
    )
    assert response.status_code == 429 and response.json()["error"]["category"] == gate.error
    assert not calls and store.audits[0][0].token_id == store.token_id
    assert logs[-1]["token_id"] == store.token_id


def test_invitation_credentials_in_question_never_reach_provider_or_logs(access_client):
    client, store, gate, calls, logs = access_client
    response = client.post(
        "/api/chat",
        json={"question": "Here is my code " + store.token},
        headers={"Authorization": "Bearer " + store.token},
    )
    assert response.status_code == 422 and not calls and not gate.events
    assert store.token not in json.dumps(logs)
