"""Real shared admission and usage, race admission, crash recovery and PostgreSQL ACLs."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.config import (
    AnalyticsSettings,
    DemoControlSettings,
    KnowledgeReaderSettings,
    KnowledgeWriterSettings,
    Settings,
)
from app.db.connection import create_database_engine, database_checks, migration_heads
from app.demo_gate import AdmissionError, DemoGate
from scripts.demo_policy import configure, release_stale, status
from tests.test_demo_gate import policy

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("QUERYLENS_INTEGRATION") != "1",
        reason="Requires migrated, provisioned dedicated demo DB",
    ),
]


@pytest.fixture
def engines():
    owner = create_database_engine(Settings())
    control = create_database_engine(DemoControlSettings())
    with owner.begin() as connection:
        for table in ("demo_leases", "demo_months", "demo_policy"):
            assert connection.scalar(text(f"SELECT count(*) FROM operations.{table}")) == 0, (
                "Use an unused dedicated test control ledger"
            )
    try:
        yield owner, control
    finally:
        with owner.begin() as connection:
            for table in ("demo_leases", "demo_months", "demo_policy"):
                connection.execute(text(f"DELETE FROM operations.{table}"))
        control.dispose()
        owner.dispose()


def test_atomic_race_across_independent_gates_and_persisted_charge(engines):
    owner, control = engines
    configured = policy(public_chat_monthly_budget_usd="1")
    configure(owner, configured)

    def attempt(_):
        gate = DemoGate(control, configured)
        try:
            request_id = uuid4().hex
            gate.admit(request_id)
            return request_id
        except AdmissionError as exc:
            return exc.category

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(attempt, range(4)))
    assert results.count("demo_busy") == 3
    winner = next(result for result in results if result != "demo_busy")
    snapshot = status(owner)
    assert len(snapshot["leases"]) == 1
    assert snapshot["months"][0]["charged_micro_usd"] == 0
    with pytest.raises(ValueError, match="Active leases"):
        configure(owner, configured)
    with pytest.raises(AdmissionError, match="demo_busy"):
        DemoGate(control, configured).admit(uuid4().hex)
    release_stale(owner, winner)
    assert status(owner)["months"][0]["charged_micro_usd"] == 0
    assert status(owner)["months"][0]["unknown_requests"] == 1
    fresh = uuid4().hex
    DemoGate(control, configured).admit(fresh)
    DemoGate(control, configured).release(fresh)
    assert len(status(owner)["leases"]) == 0
    assert status(owner)["months"][0]["unknown_requests"] == 2
    assert status(owner)["months"][0]["charged_micro_usd"] == 0


def test_monthly_budget_rate_window_and_policy_changes_do_not_reset_charges(engines):
    owner, control = engines
    configured = policy(public_chat_monthly_budget_usd="1", public_chat_requests_per_minute=1)
    configured = replace(configured, monthly_micro_usd=7400)
    configure(owner, configured)
    gate = DemoGate(control, configured)
    first = uuid4().hex
    gate.admit(first)
    from tests.test_costs import reported_usage

    gate.release(first, result=reported_usage())
    with pytest.raises(AdmissionError, match="demo_rate_limit"):
        gate.admit(uuid4().hex)
    with owner.begin() as connection:
        connection.execute(
            text("UPDATE operations.demo_months SET rate_minute=rate_minute-interval '1 minute'")
        )
    with pytest.raises(AdmissionError, match="demo_budget_exhausted"):
        gate.admit(uuid4().hex)
    assert status(owner)["months"][0]["rate_count"] == 1
    configure(owner, configured)
    assert status(owner)["months"][0]["charged_micro_usd"] == 7400
    with pytest.raises(AdmissionError, match="demo_policy_mismatch"):
        DemoGate(control, replace(configured, fingerprint="different-policy")).admit(uuid4().hex)


def test_missing_policy_and_zero_budget_fail_before_admission(engines):
    owner, control = engines
    configured = policy()
    gate = DemoGate(control, configured)
    with pytest.raises(AdmissionError, match="demo_policy_mismatch"):
        gate.admit(uuid4().hex)
    configure(owner, configured)
    with pytest.raises(AdmissionError, match="demo_budget_exhausted"):
        gate.admit(uuid4().hex)
    assert status(owner)["months"] == [] and status(owner)["leases"] == []


def test_control_role_health_and_forbidden_data_and_policy_writes(engines):
    _, control = engines
    assert all(database_checks(control, migration_heads()).values())
    for statement in (
        "SELECT * FROM analytics.orders",
        "SELECT * FROM knowledge.chunks",
        "UPDATE operations.demo_policy SET fingerprint='unsafe'",
        "CREATE TABLE public.unsafe_probe(id int)",
    ):
        with control.begin() as connection, pytest.raises(DBAPIError) as exc:
            connection.execute(text(statement))
        assert exc.value.orig.pgcode == "42501"
    for settings_type in (AnalyticsSettings, KnowledgeReaderSettings, KnowledgeWriterSettings):
        engine = create_database_engine(settings_type())
        try:
            with engine.connect() as connection, pytest.raises(DBAPIError) as exc:
                connection.execute(text("SELECT * FROM operations.demo_months"))
            assert exc.value.orig.pgcode == "42501"
        finally:
            engine.dispose()


def test_failed_release_preserves_lease_and_fails_closed(engines):
    owner, control = engines
    configured = policy(public_chat_monthly_budget_usd="1")
    configure(owner, configured)
    request_id = uuid4().hex
    gate = DemoGate(control, configured)
    gate.admit(request_id)
    with owner.begin() as connection:
        connection.execute(
            text("REVOKE DELETE ON operations.demo_leases FROM querylens_demo_control")
        )
    try:
        with pytest.raises(AdmissionError, match="demo_controls_unavailable"):
            gate.release(request_id)
        assert status(owner)["leases"][0]["request_id"] == request_id
        with pytest.raises(AdmissionError, match="demo_busy"):
            gate.admit(uuid4().hex)
    finally:
        with owner.begin() as connection:
            connection.execute(
                text("GRANT DELETE ON operations.demo_leases TO querylens_demo_control")
            )


def test_public_http_startup_and_zero_budget_use_no_owner_or_provider(engines, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import EmbeddingSettings, LLMSettings, PublicDemoSettings
    from app.demo_gate import DemoPolicy
    from app.main import create_app

    owner, _ = engines
    demo = PublicDemoSettings(_env_file=None, public_demo_enabled=True)
    configured = DemoPolicy.from_settings(demo, LLMSettings(), EmbeddingSettings())
    configure(owner, configured)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setattr("app.api.chat.ask", lambda *a, **k: pytest.fail("No paid call allowed"))
    with TestClient(create_app(demo_settings=demo)) as client:
        assert client.app.state.engine.url.username == "querylens_demo_control"
        assert client.get("/health/ready").status_code == 200
        assert client.get("/").status_code == 200
        response = client.post("/api/chat", json={"question": "Revenue?"})
        assert response.status_code == 429
        assert response.json()["error"]["category"] == "demo_budget_exhausted"
    assert status(owner)["months"] == []


def test_new_utc_month_has_separate_allocation_and_keeps_old_charge(engines):
    owner, control = engines
    configured = policy(public_chat_monthly_budget_usd="1")
    configure(owner, configured)
    gate = DemoGate(control, configured)
    request_id = uuid4().hex
    gate.admit(request_id)
    gate.release(request_id)
    with owner.begin() as connection:
        connection.execute(
            text("UPDATE operations.demo_months SET month=(month-interval '1 month')::date")
        )
    request_id = uuid4().hex
    gate.admit(request_id)
    gate.release(request_id)
    months = status(owner)["months"]
    assert len(months) == 2
    assert all(row["charged_micro_usd"] == 0 for row in months)


def test_locked_admission_times_out_without_charging(engines):
    from app.demo_gate import LOCK

    owner, control = engines
    configured = policy(public_chat_monthly_budget_usd="1")
    configure(owner, configured)
    with owner.connect() as blocker:
        blocker.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK})
        try:
            with pytest.raises(AdmissionError, match="demo_controls_unavailable"):
                DemoGate(control, configured).admit(uuid4().hex)
            assert status(owner)["months"] == [] and status(owner)["leases"] == []
        finally:
            blocker.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK})
