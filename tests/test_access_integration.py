"""Real PostgreSQL admission/credentials/ACLs; no provider or production credentials."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.access import AccessStore
from app.config import (
    AnalyticsSettings,
    DemoControlSettings,
    KnowledgeReaderSettings,
    KnowledgeWriterSettings,
    Settings,
)
from app.db.connection import create_database_engine
from app.demo_gate import AdmissionError, DemoGate
from scripts.access_tokens import (
    TokenOptions,
    create_token,
    list_tokens,
    revoke_token,
    token_usage,
    update_token,
)
from scripts.demo_policy import configure, release_stale, status
from tests.test_demo_gate import policy

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("QUERYLENS_INTEGRATION") != "1",
        reason="Requires unused dedicated migrated/provisioned demo DB",
    ),
]


@pytest.fixture
def access_db():
    owner, control = (
        create_database_engine(Settings()),
        create_database_engine(DemoControlSettings()),
    )
    tables = (
        "access_requests",
        "access_sessions",
        "access_usage",
        "access_tokens",
        "demo_leases",
        "demo_months",
        "demo_policy",
    )
    with owner.connect() as connection:
        for table in tables:
            assert connection.scalar(text(f"SELECT count(*) FROM operations.{table}")) == 0
    try:
        configured = policy(
            public_chat_monthly_budget_usd="5",
            public_chat_requests_per_minute=60,
            public_chat_max_concurrent=4,
        )
        configure(owner, configured)
        yield owner, control, configured
    finally:
        with owner.begin() as connection:
            for table in tables:
                connection.execute(text(f"DELETE FROM operations.{table}"))
        owner.dispose()
        control.dispose()


def issue(owner, tmp_path, **options):
    path = tmp_path / (uuid4().hex + ".txt")
    result = create_token(
        owner, TokenOptions(**{"name": "Disposable offline company", **options}), path
    )
    return result["token_id"], path.read_text().strip(), path, result


def test_only_digests_are_stored_and_reports_never_reveal_secrets(access_db, tmp_path):
    owner, control, configured = access_db
    tid, credential, path, result = issue(owner, tmp_path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert credential not in json.dumps(result, default=str)
    assert "secret_digest" not in json.dumps(list_tokens(owner), default=str)
    store = AccessStore(control)
    identity = store.authenticate(credential)
    assert identity.token_id == tid and identity.session_id is None
    with pytest.raises(AdmissionError, match="access_denied"):
        store.authenticate(credential[:-1] + ("A" if credential[-1] != "A" else "B"))
    with owner.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT secret_digest FROM operations.access_tokens WHERE id=:id"), {"id": tid}
            )
            != credential
        )
    session, age, browser = store.create_session(credential, 300)
    assert session != credential and age == 300
    assert store.authenticate(session, session=True) == browser
    assert credential not in json.dumps(token_usage(owner, tid), default=str)
    with pytest.raises(FileExistsError):
        create_token(owner, TokenOptions(name="Other company"), path)
    assert path.read_text().strip() == credential and len(list_tokens(owner)) == 1


def test_parallel_gates_cannot_exceed_a_token_lifetime_request_quota(access_db, tmp_path):
    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path, max_requests=1)
    store = AccessStore(control)
    identity = store.authenticate(credential)

    def attempt(_):
        request = uuid4().hex
        try:
            DemoGate(control, configured).admit(request, identity=identity)
            return request
        except AdmissionError as error:
            return error.category

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count("access_request_limit") == 3
    assert status(owner)["months"][0]["charged_micro_usd"] == configured.request_micro_usd
    report = token_usage(owner, tid)
    assert report["token"]["admitted_requests"] == 1
    assert report["token"]["reserved_micro_usd"] == configured.request_micro_usd
    assert len(report["requests"]) == 1 and report["requests"][0]["completed_at"] is None
    assert store.status(identity, configured)["remaining_requests"] == 0
    release_stale(owner, next(value for value in results if value != "access_request_limit"))
    report = token_usage(owner, tid)
    assert report["requests"][0]["summary"]["error_category"] == "request_interrupted"
    assert report["token"]["reserved_micro_usd"] == configured.request_micro_usd


@pytest.mark.parametrize(
    "options,error",
    [
        ({"budget_usd": Decimal("0.114320")}, "access_budget_exhausted"),
        ({"requests_per_minute": 1}, "access_rate_limit"),
    ],
)
def test_token_budget_and_rate_denials_roll_back_global_and_token_counters(
    access_db, tmp_path, options, error
):
    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path, **options)
    identity = AccessStore(control).authenticate(credential)
    gate = DemoGate(control, configured)
    first = uuid4().hex
    gate.admit(first, identity=identity)
    gate.release(first)
    before = status(owner)
    with pytest.raises(AdmissionError, match=error):
        gate.admit(uuid4().hex, identity=identity)
    assert status(owner) == before
    assert token_usage(owner, tid)["token"]["admitted_requests"] == 1


def test_global_denial_does_not_consume_a_tokens_allowance(access_db, tmp_path):
    owner, control, configured = access_db
    configured = policy(public_chat_monthly_budget_usd="0")
    configure(owner, configured)
    tid, credential, _, _ = issue(owner, tmp_path)
    identity = AccessStore(control).authenticate(credential)
    with pytest.raises(AdmissionError, match="demo_budget_exhausted"):
        DemoGate(control, configured).admit(uuid4().hex, identity=identity)
    assert token_usage(owner, tid)["token"]["admitted_requests"] == 0
    assert status(owner)["months"] == []


def test_revoke_and_expiry_reject_existing_sessions_and_stale_authenticated_identities(
    access_db, tmp_path
):
    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path)
    store = AccessStore(control)
    session, _, browser = store.create_session(credential, 300)
    revoke_token(owner, tid)
    for value, session_mode in ((credential, False), (session, True)):
        with pytest.raises(AdmissionError, match="access_denied"):
            store.authenticate(value, session=session_mode)
    with pytest.raises(AdmissionError, match="access_denied"):
        DemoGate(control, configured).admit(uuid4().hex, identity=browser)
    assert status(owner)["months"] == []
    with pytest.raises(ValueError, match="Revoked"):
        update_token(owner, tid, {"max_requests": 10})
    tid2, credential2, _, _ = issue(owner, tmp_path)
    with owner.begin() as connection:
        connection.execute(
            text(
                "UPDATE operations.access_tokens "
                "SET expires_at=created_at+interval '1 microsecond' "
                "WHERE id=:id"
            ),
            {"id": tid2},
        )
    with pytest.raises(AdmissionError, match="access_denied"):
        store.authenticate(credential2)


def test_session_expiry_logout_and_bounded_session_count(access_db, tmp_path):
    owner, control, configured = access_db
    _, credential, _, _ = issue(owner, tmp_path)
    store = AccessStore(control)
    session, _, browser = store.create_session(credential, 300)
    store.logout(session)
    with pytest.raises(AdmissionError):
        DemoGate(control, configured).admit(uuid4().hex, identity=browser)
    assert status(owner)["months"] == []
    session, _, browser = store.create_session(credential, 300)
    with owner.begin() as connection:
        connection.execute(
            text(
                "UPDATE operations.access_sessions "
                "SET expires_at=created_at+interval '1 microsecond' WHERE id=:id"
            ),
            {"id": browser.session_id},
        )
    with pytest.raises(AdmissionError):
        store.authenticate(session, session=True)
    for _ in range(8):
        store.create_session(credential, 300)
    with pytest.raises(AdmissionError, match="access_session_limit"):
        store.create_session(credential, 300)


def test_usage_audit_is_durable_sanitized_and_counts_failed_admitted_requests(access_db, tmp_path):
    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path)
    store, gate = AccessStore(control), DemoGate(control, configured)
    identity = store.authenticate(credential)
    request = uuid4().hex
    gate.admit(request, identity=identity)
    gate.release(request)
    private = "private question SQL credential marker"
    result = {
        "status": "error",
        "error": {"category": "ungrounded_answer", "message": private},
        "usage": {
            "model": "gpt-5.4-mini",
            "requests": 2,
            "input_tokens": 123,
            "output_tokens": 45,
            "usage_complete": True,
        },
        "question": private,
        "explanation": private,
        "sources": [{"content": private}],
    }
    assert store.audit(identity, request, result, 100, 200)
    denied = uuid4().hex
    assert store.audit(
        identity, denied, {"status": "error", "error": {"category": "access_rate_limit"}}, 20, 429
    )
    report = token_usage(owner, tid)
    assert report["token"]["admitted_requests"] == 1 and len(report["requests"]) == 2
    assert private not in json.dumps(report, default=str) and credential not in json.dumps(
        report, default=str
    )
    admitted = next(row for row in report["requests"] if row["request_id"] == request)
    assert (
        admitted["summary"]["llm_requests"] == 2
        and admitted["summary"]["error_category"] == "ungrounded_answer"
    )
    assert admitted["reserved_micro_usd"] == configured.request_micro_usd
    assert all(row["completed_at"] is not None for row in report["requests"])
    update_token(owner, tid, {"max_requests": 10, "budget_usd": "1", "name": "Renamed company"})
    after = token_usage(owner, tid)["token"]
    assert after["name"] == "Renamed company" and after["admitted_requests"] == 1
    assert after["reserved_micro_usd"] == configured.request_micro_usd


def test_runtime_role_cannot_issue_revoke_or_change_policy_and_readers_cannot_read_tokens(
    access_db,
):
    owner, control, _ = access_db
    for query in (
        "UPDATE operations.access_tokens SET revoked_at=clock_timestamp()",
        "DELETE FROM operations.access_tokens",
        "INSERT INTO operations.access_tokens(id) VALUES ('forged')",
        "UPDATE operations.access_requests SET reserved_micro_usd=0",
        "DELETE FROM operations.access_requests",
    ):
        with pytest.raises(DBAPIError), control.begin() as connection:
            connection.execute(text(query))
    for settings_class in (AnalyticsSettings, KnowledgeReaderSettings, KnowledgeWriterSettings):
        engine = create_database_engine(settings_class())
        try:
            for table in ("access_tokens", "access_sessions", "access_requests"):
                with pytest.raises(DBAPIError), engine.connect() as connection:
                    connection.execute(text(f"SELECT * FROM operations.{table}"))
        finally:
            engine.dispose()


def test_real_http_access_readiness_failed_request_accounting_and_safe_attribution(
    access_db, tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    from app.config import AccessSettings, PublicDemoSettings
    from app.main import create_app

    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(
        "app.llm.openai_provider.OpenAI",
        lambda *a, **k: pytest.fail("Must not construct a provider with no API key"),
    )
    demo = PublicDemoSettings(
        _env_file=None,
        public_demo_enabled=True,
        public_chat_monthly_budget_usd="5",
        public_chat_requests_per_minute=60,
        public_chat_max_concurrent=4,
    )
    app = create_app(
        demo_settings=demo,
        access_settings=AccessSettings(
            _env_file=None,
            token_access_required=True,
            access_public_origin="https://querylens.test",
        ),
    )
    with TestClient(app, base_url="https://querylens.test") as client:
        assert client.get("/health/ready").json()["checks"]["access"] is True
        assert client.post("/api/chat", json={"question": "Revenue?"}).status_code == 401
        response = client.post(
            "/api/chat",
            json={"question": "Revenue?"},
            headers={"Authorization": "Bearer " + credential},
        )
        assert (
            response.status_code == 200
            and response.json()["error"]["category"] == "missing_api_key"
        )
        report = token_usage(owner, tid)
        assert report["token"]["admitted_requests"] == 1
        assert report["requests"][0]["request_id"] == response.headers["x-request-id"]
        assert report["requests"][0]["summary"]["error_category"] == "missing_api_key"
        assert report["requests"][0]["reserved_micro_usd"] == configured.request_micro_usd
        assert status(owner)["leases"] == []
        assert status(owner)["months"][0]["charged_micro_usd"] == configured.request_micro_usd
