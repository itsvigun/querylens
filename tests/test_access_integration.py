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
    assert status(owner)["months"][0]["charged_micro_usd"] == 0
    report = token_usage(owner, tid)
    assert report["token"]["admitted_requests"] == 1
    assert report["token"]["reserved_micro_usd"] == 0
    assert len(report["requests"]) == 1 and report["requests"][0]["completed_at"] is None
    assert store.status(identity, configured)["remaining_requests"] == 0
    release_stale(owner, next(value for value in results if value != "access_request_limit"))
    report = token_usage(owner, tid)
    assert report["requests"][0]["summary"]["error_category"] == "request_interrupted"
    assert report["token"]["reserved_micro_usd"] == 0


@pytest.mark.parametrize(
    "options,error",
    [
        ({"budget_usd": Decimal("0.0074")}, "access_budget_exhausted"),
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
    from tests.test_costs import reported_usage

    gate.release(first, result=reported_usage())
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
    assert admitted["reserved_micro_usd"] == 0
    assert all(row["completed_at"] is not None for row in report["requests"])
    update_token(owner, tid, {"max_requests": 10, "budget_usd": "1", "name": "Renamed company"})
    after = token_usage(owner, tid)["token"]
    assert after["name"] == "Renamed company" and after["admitted_requests"] == 1
    assert after["reserved_micro_usd"] == 0


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
        assert report["requests"][0]["reserved_micro_usd"] == 0
        assert status(owner)["leases"] == []
        assert status(owner)["months"][0]["charged_micro_usd"] == 0


def test_post_request_usage_is_counted_atomically_once_and_audit_preserves_receipt(
    access_db, tmp_path
):
    from tests.test_costs import reported_usage

    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path, budget_usd="0.114320")
    store, gate = AccessStore(control), DemoGate(control, configured)
    identity = store.authenticate(credential)
    request = uuid4().hex
    gate.admit(request, identity=identity)
    assert token_usage(owner, tid)["requests"][0]["usage_state"] == "pending"
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: gate.release(request, result=reported_usage()), range(2)))
    gate.release(request, result=reported_usage())
    report = token_usage(owner, tid)
    assert report["token"]["admitted_requests"] == 1
    assert report["token"]["reserved_micro_usd"] == 0
    assert report["token"]["charged_micro_usd"] == 7400
    assert report["requests"][0]["charged_micro_usd"] == 7400
    assert report["requests"][0]["usage_state"] == "recorded"
    assert status(owner)["months"][0]["charged_micro_usd"] == 7400
    assert status(owner)["leases"] == []
    assert store.status(identity, configured)["remaining_requests"] == 9
    assert report["requests"][0]["summary"]["billing_usage"]["input_tokens"] == 7232
    assert store.audit(identity, request, {"status": "error", **reported_usage()}, 100, 200)
    assert (
        token_usage(owner, tid)["requests"][0]["summary"]["billing_usage"]["usage_complete"] is True
    )


@pytest.mark.parametrize("failure", ["missing", "embedding", "model"])
def test_unknown_usage_has_no_invented_charge_and_cannot_be_counted_twice(
    access_db, tmp_path, failure
):
    from tests.test_costs import reported_usage

    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path)
    gate = DemoGate(control, configured)
    identity = AccessStore(control).authenticate(credential)
    request = uuid4().hex
    result = reported_usage()
    if failure == "missing":
        result = None
    elif failure == "embedding":
        result["embedding_usage"]["usage_complete"] = False
    else:
        result["usage"]["model"] = "unknown-model"
    gate.admit(request, identity=identity)
    gate.release(request, result=result)
    gate.release(request, result=reported_usage())
    assert status(owner)["months"][0]["charged_micro_usd"] == 0
    report = token_usage(owner, tid)
    assert report["token"]["unknown_requests"] == 1
    assert report["requests"][0]["charged_micro_usd"] is None
    assert report["requests"][0]["usage_state"] == "unknown"
    assert status(owner)["months"][0]["unknown_requests"] == 1


def test_shared_availability_explains_exhaustion_even_with_fresh_token_quota(access_db, tmp_path):
    owner, control, configured = access_db
    configured = policy(public_chat_monthly_budget_usd="0")
    configure(owner, configured)
    _, credential, _, _ = issue(owner, tmp_path)
    store = AccessStore(control)
    data = store.status(store.authenticate(credential), configured)
    assert data["remaining_requests"] == 10 and data["shared_available"] is False


def test_failed_accounting_rolls_back_cost_and_preserves_crash_lease(access_db, tmp_path):
    from tests.test_costs import reported_usage

    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path)
    gate = DemoGate(control, configured)
    request = uuid4().hex
    gate.admit(request, identity=AccessStore(control).authenticate(credential))
    with owner.begin() as connection:
        connection.execute(
            text(
                "REVOKE UPDATE (charged_micro_usd,usage_state) "
                "ON operations.access_requests FROM querylens_demo_control"
            )
        )
    try:
        with pytest.raises(AdmissionError, match="demo_controls_unavailable"):
            gate.release(request, result=reported_usage())
        assert status(owner)["months"][0]["charged_micro_usd"] == 0
        assert len(status(owner)["leases"]) == 1
        assert token_usage(owner, tid)["token"]["charged_micro_usd"] == 0
        assert AccessStore(control).ready() is False
    finally:
        with owner.begin() as connection:
            connection.execute(
                text(
                    "GRANT UPDATE (charged_micro_usd,usage_state) "
                    "ON operations.access_requests TO querylens_demo_control"
                )
            )


def test_small_actual_quotes_allow_more_than_eight_questions_without_raising_one_dollar(
    access_db, tmp_path
):
    from tests.test_costs import reported_usage

    owner, control, configured = access_db
    configured = policy(public_chat_monthly_budget_usd="1", public_chat_requests_per_minute=60)
    configure(owner, configured)
    tid, credential, _, _ = issue(owner, tmp_path, max_requests=10, requests_per_minute=60)
    store, gate = AccessStore(control), DemoGate(control, configured)
    identity = store.authenticate(credential)
    for _ in range(10):
        request = uuid4().hex
        gate.admit(request, identity=identity)
        gate.release(request, result=reported_usage())
    assert token_usage(owner, tid)["token"]["admitted_requests"] == 10
    assert status(owner)["months"][0]["charged_micro_usd"] == 74000
    assert store.status(identity, configured)["remaining_requests"] == 0
    with pytest.raises(AdmissionError, match="access_request_limit"):
        gate.admit(uuid4().hex, identity=identity)


def test_one_active_question_per_token_does_not_block_other_tokens(access_db, tmp_path):
    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path, requests_per_minute=60)
    _, other, _, _ = issue(owner, tmp_path)
    store, gate = AccessStore(control), DemoGate(control, configured)
    identity = store.authenticate(credential)
    first = uuid4().hex
    gate.admit(first, identity=identity)
    with ThreadPoolExecutor(max_workers=3) as pool:

        def attempt(_):
            with pytest.raises(AdmissionError, match="access_busy"):
                DemoGate(control, configured).admit(uuid4().hex, identity=identity)

        list(pool.map(attempt, range(3)))
    second = uuid4().hex
    gate.admit(second, identity=store.authenticate(other))
    assert token_usage(owner, tid)["token"]["admitted_requests"] == 1
    assert status(owner)["months"][0]["charged_micro_usd"] == 0
    gate.release(first)
    gate.release(second)


def test_last_question_can_cross_soft_budget_then_next_is_denied(access_db, tmp_path):
    from tests.test_costs import reported_usage

    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path, budget_usd="0.001")
    store, gate = AccessStore(control), DemoGate(control, configured)
    identity = store.authenticate(credential)
    request = uuid4().hex
    gate.admit(request, identity=identity)
    assert token_usage(owner, tid)["token"]["charged_micro_usd"] == 0
    gate.release(request, result=reported_usage())
    assert token_usage(owner, tid)["token"]["charged_micro_usd"] == 7400
    assert store.status(identity, configured)["budget_available"] is False
    assert store.status(identity, configured)["remaining_requests"] == 9
    before = status(owner)
    with pytest.raises(AdmissionError, match="access_budget_exhausted"):
        gate.admit(uuid4().hex, identity=identity)
    assert status(owner) == before


def test_usage_is_attributed_to_admission_month_even_when_completion_is_later(access_db, tmp_path):
    from tests.test_costs import reported_usage

    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path)
    gate = DemoGate(control, configured)
    request = uuid4().hex
    gate.admit(request, identity=AccessStore(control).authenticate(credential))
    with owner.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO "
                "operations.demo_months(month,charged_micro_usd,rate_minute,rate_count) "
                "SELECT (month-interval '1 "
                "month')::date,0,rate_minute,0 FROM operations.demo_months"
            )
        )
        connection.execute(
            text("UPDATE operations.demo_leases SET month=(month-interval '1 month')::date")
        )
    gate.release(request, result=reported_usage())
    months = status(owner)["months"]
    assert [row["charged_micro_usd"] for row in months] == [0, 7400]
    assert token_usage(owner, tid)["token"]["charged_micro_usd"] == 7400


def test_migration_archives_old_reserves_without_resetting_tokens_or_request_counts(
    access_db, tmp_path
):
    from alembic import command
    from alembic.config import Config

    from scripts.provision_roles import RolePasswords, provision_roles

    owner, control, configured = access_db
    tid, credential, _, _ = issue(owner, tmp_path)
    request = uuid4().hex
    config = Config("alembic.ini")
    try:
        command.downgrade(config, "0005_invitation_access")
        with owner.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO "
                    "operations.demo_months(month,charged_micro_usd,rate_minute,rate_count) "
                    "VALUES(date_trunc('month',clock_timestamp() AT TIME ZONE 'UTC')::date,"
                    "914560,clock_timestamp(),8)"
                )
            )
            connection.execute(
                text(
                    "UPDATE operations.access_usage SET "
                    "admitted_requests=1,reserved_micro_usd=114320 "
                    "WHERE token_id=:id"
                ),
                {"id": tid},
            )
            connection.execute(
                text(
                    "INSERT INTO operations.access_requests(request_id,token_id,created_at,"
                    "reserved_micro_usd,summary) "
                    "VALUES(:request,:token,clock_timestamp(),114320,'{}')"
                ),
                {"request": request, "token": tid},
            )
            connection.execute(
                text(
                    "INSERT INTO operations.demo_leases(request_id,admitted_at,month) "
                    "SELECT :id,clock_timestamp(),month FROM operations.demo_months"
                ),
                {"id": request},
            )
        with pytest.raises(RuntimeError, match="Stop/drain"):
            command.upgrade(config, "head")
        with owner.begin() as connection:
            assert (
                connection.scalar(text("SELECT charged_micro_usd FROM operations.demo_months"))
                == 914560
            )
            connection.execute(
                text("DELETE FROM operations.demo_leases WHERE request_id=:id"), {"id": request}
            )
        command.upgrade(config, "head")
        provision_roles(Settings(), RolePasswords())
        month = status(owner)["months"][0]
        assert month["legacy_reserved_micro_usd"] == 914560
        assert month["charged_micro_usd"] == 0 and month["rate_count"] == 8
        report = token_usage(owner, tid)
        assert report["token"]["reserved_micro_usd"] == 114320
        assert report["token"]["admitted_requests"] == 1
        assert report["requests"][0]["usage_state"] == "legacy"
        assert report["requests"][0]["charged_micro_usd"] is None
        identity = AccessStore(control).authenticate(credential)
        assert AccessStore(control).status(identity, configured)["remaining_requests"] == 9
        fresh = uuid4().hex
        DemoGate(control, configured).admit(fresh, identity=identity)
        DemoGate(control, configured).release(fresh)
    finally:
        command.upgrade(config, "head")
        provision_roles(Settings(), RolePasswords())
