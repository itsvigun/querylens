"""Capture real JSON log boundaries and prove submitted data cannot enter them."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.llm import service
from app.main import create_app
from app.observability import LOGGER, REQUEST_ID, summary

SECRET = "sk-private-token postgres://owner:password@host\nINJECTED LOG LINE"


@pytest.fixture
def records():
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(json.loads(record.getMessage()))

    handler = Capture()
    LOGGER.addHandler(handler)
    try:
        yield records
    finally:
        LOGGER.removeHandler(handler)


def answer():
    return {
        "status": "answered",
        "explanation": SECRET,
        "facts": [],
        "queries": [{"executed_sql": SECRET, "rows": [[SECRET]]}],
        "sources": [{"content": SECRET}],
        "usage": {
            "model": "gpt-5.4-mini",
            "requests": 3,
            "input_tokens": 100,
            "output_tokens": 20,
            "usage_complete": True,
        },
        "workflow": {"tool_calls": 3, "sql_attempts": 1, "sql_repairs": 0},
        "embedding_usage": {"model": "text-embedding-3-small", "requests": 1, "prompt_tokens": 8},
    }


def test_cli_logs_one_allowlisted_summary_without_payload(monkeypatch, records):
    monkeypatch.setattr(service, "_ask", lambda *a, **k: answer())
    result = service.ask(SECRET)
    assert len(records) == 1
    event = records[0]
    UUID(event["request_id"])
    assert result["request_id"] == event["request_id"]
    assert event["input_tokens"] == 100 and event["sql_attempts"] == 1
    assert event["embedding_tokens"] == 8 and event["model"] == "gpt-5.4-mini"
    assert SECRET not in json.dumps(records)
    assert set(event).isdisjoint({"question", "queries", "sources", "messages", "facts"})


def test_api_uses_server_generated_id_and_one_log(monkeypatch, settings, records):
    monkeypatch.setattr(service, "_ask", lambda *a, **k: answer())
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/chat", json={"question": SECRET}, headers={"X-Request-ID": SECRET}
        )
        client.get("/demo")
    assert response.status_code == 200
    assert len(records) == 1
    request_id = response.headers["X-Request-ID"]
    assert response.json()["request_id"] == records[0]["request_id"] == request_id
    UUID(request_id)
    assert records[0]["http_status"] == 200
    assert SECRET not in json.dumps(records)
    assert REQUEST_ID.get() is None


@pytest.mark.parametrize("status", [422, 429, 500])
def test_validation_busy_and_unexpected_errors_are_sanitized(
    status, monkeypatch, settings, records
):
    application = create_app(settings)

    def fail(*a, **k):
        raise RuntimeError(SECRET)

    monkeypatch.setattr("app.api.chat.ask", fail)
    with TestClient(application) as client:
        if status == 429:
            application.state.chat_lock.acquire()
        payload = {"question": "Revenue?"} if status != 422 else {"api_key": SECRET}
        response = client.post("/api/chat", json=payload)
        if status == 429:
            application.state.chat_lock.release()
    assert response.status_code == status
    assert len(records) == 1 and records[0]["http_status"] == status
    assert (
        records[0]["error_category"]
        == {422: "invalid_request", 429: "busy", 500: "request_failed"}[status]
    )
    assert SECRET not in response.text and SECRET not in json.dumps(records)


def test_unknown_identifier_and_counts_cannot_expose_secrets():
    result = {
        "status": SECRET,
        "error": {"category": SECRET},
        "usage": {
            "model": SECRET,
            "input_tokens": SECRET,
            "output_tokens": True,
            "requests": -1,
            "usage_complete": SECRET,
        },
        "embedding_usage": {"model": SECRET, "requests": SECRET},
    }
    event = summary(result)
    assert SECRET not in json.dumps(event)
    assert event["error_category"] == "request_failed"
    assert event["input_tokens"] is event["output_tokens"] is event["llm_requests"] is None
    assert not event["usage_complete"]


def test_cli_exception_does_not_log_exception_text(monkeypatch, records):
    def fail(*a, **k):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(service, "_ask", fail)
    result = service.ask(SECRET)
    assert result["error"]["category"] == "request_failed"
    assert SECRET not in json.dumps(records)


def test_concurrent_cli_requests_have_distinct_ids(monkeypatch, records):
    monkeypatch.setattr(service, "_ask", lambda *a, **k: answer())
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(service.ask, ["Revenue?"] * 3))
    assert len({r["request_id"] for r in results}) == len(records) == 3
