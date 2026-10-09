"""Public HTTP admission and bounded bodies without paid providers or PostgreSQL."""

import asyncio
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.body_limit import ChatBodyLimitMiddleware
from app.config import DemoControlSettings, EmbeddingSettings, LLMSettings, PublicDemoSettings
from app.demo_gate import AdmissionError, DemoPolicy
from app.main import create_app


def policy(**changes):
    return DemoPolicy.from_settings(
        PublicDemoSettings(_env_file=None, public_demo_enabled=True, **changes),
        LLMSettings(_env_file=None),
        EmbeddingSettings(_env_file=None),
    )


def test_reservation_decimal_pricing_and_no_key_in_policy():
    current = policy(public_chat_monthly_budget_usd="1.25")
    assert current.monthly_micro_usd == 1_250_000
    assert current.request_micro_usd == 114_320
    demo = PublicDemoSettings(_env_file=None)
    base = DemoPolicy.from_settings(
        demo, LLMSettings(_env_file=None), EmbeddingSettings(_env_file=None)
    )
    keyed = DemoPolicy.from_settings(
        demo,
        LLMSettings(_env_file=None, openai_api_key="secret-a"),
        EmbeddingSettings(_env_file=None, openai_api_key="secret-b"),
    )
    assert keyed == base
    assert policy(public_chat_monthly_budget_usd="2").fingerprint != current.fingerprint


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-0.01", "0.0000001", "100.01"])
def test_invalid_public_budgets_rejected(amount):
    with pytest.raises(ValidationError):
        policy(public_chat_monthly_budget_usd=amount)


def test_railway_cannot_start_without_public_controls():
    with pytest.raises(ValidationError, match="Railway requires public demo controls"):
        PublicDemoSettings(_env_file=None, railway_environment_id="test-environment")


def test_control_role_never_uses_owner_secret(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "owner-only-password")
    monkeypatch.delenv("DEMO_CONTROL_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        DemoControlSettings(_env_file=None)
    configured = DemoControlSettings(_env_file=None, DEMO_CONTROL_PASSWORD="control-only-password")
    assert configured.database_url.username == "querylens_demo_control"
    assert configured.database_url.password == "control-only-password"


class Gate:
    def __init__(self, category=None, release_error=False):
        self.category = category
        self.release_error = release_error
        self.events = []

    def admit(self, request_id):
        UUID(request_id)
        self.events.append(("admit", request_id))
        if self.category:
            raise AdmissionError(self.category, 429, 5)

    def release(self, request_id):
        self.events.append(("release", request_id))
        if self.release_error:
            raise AdmissionError("demo_controls_unavailable")


@pytest.mark.parametrize(
    "category",
    [
        "demo_busy",
        "demo_rate_limit",
        "demo_budget_exhausted",
        "demo_policy_mismatch",
        "demo_controls_unavailable",
    ],
)
def test_denial_never_calls_provider_or_releases_unadmitted_lease(category, settings, monkeypatch):
    calls = []
    monkeypatch.setattr("app.api.chat.ask", lambda *a, **k: calls.append(a))
    with TestClient(create_app(settings)) as client:
        gate = Gate(category)
        client.app.state.demo_gate = gate
        response = client.post("/api/chat", json={"question": "Revenue?"})
        assert client.app.state.chat_lock.acquire(blocking=False)
        client.app.state.chat_lock.release()
    assert calls == []
    assert response.status_code == 429
    assert response.json()["error"]["category"] == category
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["Retry-After"] == "5"
    assert len(gate.events) == 1


@pytest.mark.parametrize("failure", [None, "ask", "release"])
def test_success_and_failures_release_shared_lease(settings, monkeypatch, failure):
    configured = LLMSettings(_env_file=None)
    embeddings = EmbeddingSettings(_env_file=None)

    def fake_ask(question, **kwargs):
        assert kwargs == {"settings": configured, "embedding_settings": embeddings}
        if failure == "ask":
            raise RuntimeError("private-test-secret")
        return {"status": "unsupported", "explanation": "Offline fixture"}

    monkeypatch.setattr("app.api.chat.ask", fake_ask)
    with TestClient(create_app(settings)) as client:
        gate = Gate(release_error=failure == "release")
        client.app.state.demo_gate = gate
        client.app.state.llm_settings = configured
        client.app.state.embedding_settings = embeddings
        response = client.post("/api/chat", json={"question": "Revenue?"})
    assert response.status_code == {None: 200, "ask": 500, "release": 503}[failure]
    assert "private-test-secret" not in response.text
    assert [item[0] for item in gate.events] == ["admit", "release"]
    assert gate.events[0][1] == gate.events[1][1]


def test_large_http_body_is_rejected_before_provider(settings, monkeypatch):
    calls = []
    monkeypatch.setattr("app.api.chat.ask", lambda *a, **k: calls.append(a))
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/chat", content=b"private-test-secret" * 2000)
    assert response.status_code == 413
    assert "private-test-secret" not in response.text
    assert "X-Request-ID" in response.headers
    assert not calls


def test_chunked_body_stops_receiving_after_limit_without_parsing():
    messages = iter(
        [
            {"type": "http.request", "body": b"a" * 8000, "more_body": True},
            {"type": "http.request", "body": b"b" * 9000, "more_body": True},
        ]
    )
    received, sent, called = [], [], []

    async def receive():
        received.append(True)
        return next(messages)

    async def send(message):
        sent.append(message)

    async def app(*args):
        called.append(True)

    scope = {"type": "http", "path": "/api/chat", "method": "POST", "headers": []}
    asyncio.run(ChatBodyLimitMiddleware(app)(scope, receive, send))
    assert len(received) == 2 and not called
    assert sent[0]["status"] == 413


def test_dynamic_port_entrypoint_keeps_proxy_and_access_logs_disabled(monkeypatch):
    from scripts import serve

    captured = []
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setattr(serve.uvicorn, "run", lambda *a, **k: captured.append((a, k)))
    serve.main()
    assert captured[0][1]["port"] == 9123
    assert captured[0][1]["access_log"] is False
    assert captured[0][1]["proxy_headers"] is False
    assert policy().monthly_micro_usd == Decimal("0")


def test_foundation_job_stops_on_failure_without_logging_child_output(monkeypatch, capsys):
    import subprocess

    from scripts import deploy_setup

    calls = []
    monkeypatch.setattr(
        deploy_setup,
        "PublicDemoSettings",
        lambda: type("Demo", (), {"public_demo_enabled": True})(),
    )
    monkeypatch.setattr(deploy_setup, "DemoControlSettings", lambda: None)

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["capture_output"] is True and kwargs["timeout"] == 180
        if command[2] == "scripts.seed":
            raise subprocess.CalledProcessError(1, command, output="private-test-secret")

    monkeypatch.setattr(deploy_setup.subprocess, "run", run)
    assert deploy_setup.main() == 1
    assert len(calls) == 3
    assert "private-test-secret" not in capsys.readouterr().out
    assert all("ingest" not in " ".join(command) for command in calls)


def test_control_password_validation_text_does_not_reveal_secret():
    with pytest.raises(ValidationError) as exc:
        DemoControlSettings(_env_file=None, DEMO_CONTROL_PASSWORD="short-private")
    assert "short-private" not in str(exc.value)


def test_public_local_busy_response_uses_same_category_and_retry_hint(settings, monkeypatch):
    monkeypatch.setattr("app.api.chat.ask", lambda *a, **k: pytest.fail("No provider permitted"))
    with TestClient(create_app(settings)) as client:
        gate = Gate()
        client.app.state.demo_gate = gate
        client.app.state.chat_lock.acquire()
        try:
            response = client.post("/api/chat", json={"question": "Revenue?"})
        finally:
            client.app.state.chat_lock.release()
    assert response.status_code == 429
    assert response.json()["error"]["category"] == "demo_busy"
    assert response.headers["Retry-After"] == "5"
    assert not gate.events
