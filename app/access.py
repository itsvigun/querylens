"""Opaque invitation credentials, short browser sessions and bounded usage audit."""

import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import and_, func, literal_column, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.demo_gate import LOCK, AdmissionError
from app.observability import summary

CREDENTIAL = re.compile(r"(qlt|qls)_([a-f0-9]{32})_([A-Za-z0-9_-]{43})", re.ASCII)


def issue_credential(kind: str) -> tuple[str, str, str]:
    identifier = uuid4().hex
    credential = f"{kind}_{identifier}_{secrets.token_urlsafe(32)}"
    return identifier, credential, sha256(credential.encode()).hexdigest()


def credential_parts(credential: str, kind: str) -> tuple[str, str]:
    match = CREDENTIAL.fullmatch(credential) if isinstance(credential, str) else None
    if match is None or match[1] != kind:
        raise AdmissionError("access_denied", 401)
    return match[2], sha256(credential.encode()).hexdigest()


def csrf_value(session: str) -> str:
    return hmac.new(session.encode(), b"querylens-csrf-v1", sha256).hexdigest()


@dataclass(frozen=True)
class AccessIdentity:
    token_id: str
    session_id: str | None = None


def valid_identity(connection, identity: AccessIdentity, now):
    token = (
        connection.execute(
            text("SELECT * FROM operations.access_tokens WHERE id=:id"),
            {"id": identity.token_id},
        )
        .mappings()
        .one_or_none()
    )
    if token is None or token["revoked_at"] is not None or token["expires_at"] <= now:
        raise AdmissionError("access_denied", 401)
    if identity.session_id is not None:
        session = connection.execute(
            text("SELECT token_id, expires_at FROM operations.access_sessions WHERE id=:id"),
            {"id": identity.session_id},
        ).one_or_none()
        if session is None or session.token_id != identity.token_id or session.expires_at <= now:
            raise AdmissionError("access_denied", 401)
    return token


def admit_access(connection, identity, request_id, now, pricing_version):
    """Called inside the same locked transaction as global admission; denials roll back."""
    token = valid_identity(connection, identity, now)
    usage = (
        connection.execute(
            text("SELECT * FROM operations.access_usage WHERE token_id=:id"),
            {"id": identity.token_id},
        )
        .mappings()
        .one()
    )
    if usage["admitted_requests"] >= token["max_requests"]:
        raise AdmissionError("access_request_limit", 429)
    if usage["charged_micro_usd"] >= token["budget_micro_usd"]:
        raise AdmissionError("access_budget_exhausted", 429)
    if connection.scalar(
        text(
            "SELECT count(*) FROM operations.demo_leases l "
            "JOIN operations.access_requests r ON r.request_id=l.request_id "
            "WHERE r.token_id=:id"
        ),
        {"id": identity.token_id},
    ):
        raise AdmissionError("access_busy", 429, 5)
    minute = now.replace(second=0, microsecond=0)
    count = usage["rate_count"] if usage["rate_minute"] == minute else 0
    if count >= token["requests_per_minute"]:
        raise AdmissionError("access_rate_limit", 429, 60 - now.second)
    connection.execute(
        text(
            "UPDATE operations.access_usage SET admitted_requests=admitted_requests+1, "
            "rate_minute=:minute, "
            "rate_count=:count, first_used_at=COALESCE(first_used_at,:now), last_used_at=:now "
            "WHERE token_id=:id"
        ),
        {
            "id": identity.token_id,
            "minute": minute,
            "count": count + 1,
            "now": now,
        },
    )
    connection.execute(
        text(
            "INSERT INTO operations.access_requests "
            "(request_id,token_id,created_at,reserved_micro_usd,charged_micro_usd,"
            "usage_state,pricing_version,summary) "
            "VALUES (:request,:token,:now,0,NULL,'pending',:pricing,'{}'::jsonb)"
        ),
        {
            "request": request_id,
            "token": identity.token_id,
            "now": now,
            "pricing": pricing_version,
        },
    )


class AccessStore:
    def __init__(self, engine):
        self.engine = engine

    def ready(self):
        actor = literal_column("current_user")
        checks = [
            actor == "querylens_demo_control",
            ~func.has_table_privilege(actor, "operations.access_tokens", "INSERT,UPDATE,DELETE"),
        ]
        for relation, privileges in (
            ("access_tokens", ("SELECT",)),
            ("access_usage", ("SELECT", "UPDATE")),
            ("access_sessions", ("SELECT", "INSERT", "DELETE")),
            ("access_requests", ("SELECT", "INSERT")),
        ):
            checks.extend(
                func.has_table_privilege(actor, "operations." + relation, action)
                for action in privileges
            )
        checks.extend(
            func.has_column_privilege(actor, "operations.access_requests", column, "UPDATE")
            for column in ("summary", "completed_at", "charged_micro_usd", "usage_state")
        )
        with self.engine.connect() as connection:
            return connection.scalar(select(and_(*checks))) is True

    def authenticate(self, credential: str, *, session=False) -> AccessIdentity:
        identifier, digest = credential_parts(credential, "qls" if session else "qlt")
        try:
            with self.engine.connect() as connection:
                now = connection.scalar(text("SELECT clock_timestamp()"))
                if session:
                    row = connection.execute(
                        text(
                            "SELECT token_id,secret_digest,expires_at "
                            "FROM operations.access_sessions WHERE id=:id"
                        ),
                        {"id": identifier},
                    ).one_or_none()
                    token_id = row.token_id if row is not None else identifier
                else:
                    row = connection.execute(
                        text("SELECT secret_digest FROM operations.access_tokens WHERE id=:id"),
                        {"id": identifier},
                    ).one_or_none()
                    token_id = identifier
                expected = row.secret_digest if row is not None else "0" * 64
                if not hmac.compare_digest(digest, expected) or row is None:
                    raise AdmissionError("access_denied", 401)
                identity = AccessIdentity(token_id, identifier if session else None)
                valid_identity(connection, identity, now)
                return identity
        except SQLAlchemyError, OSError:
            raise AdmissionError("access_unavailable") from None

    def create_session(self, credential: str, ttl: int) -> tuple[str, int, AccessIdentity]:
        identity = self.authenticate(credential)
        session_id, session, digest = issue_credential("qls")
        try:
            with self.engine.begin() as connection:
                connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
                now = connection.scalar(text("SELECT clock_timestamp()"))
                token = valid_identity(connection, identity, now)
                connection.execute(
                    text("DELETE FROM operations.access_sessions WHERE expires_at<=:now"),
                    {"now": now},
                )
                if (
                    connection.scalar(
                        text("SELECT count(*) FROM operations.access_sessions WHERE token_id=:id"),
                        {"id": identity.token_id},
                    )
                    >= 8
                ):
                    raise AdmissionError("access_session_limit", 429)
                expires = min(token["expires_at"], now + timedelta(seconds=ttl))
                connection.execute(
                    text(
                        "INSERT INTO operations.access_sessions "
                        "(id,token_id,secret_digest,created_at,expires_at) "
                        "VALUES (:id,:token,:digest,:now,:expires)"
                    ),
                    {
                        "id": session_id,
                        "token": identity.token_id,
                        "digest": digest,
                        "now": now,
                        "expires": expires,
                    },
                )
            return (
                session,
                int((expires - now).total_seconds()),
                AccessIdentity(identity.token_id, session_id),
            )
        except SQLAlchemyError, OSError:
            raise AdmissionError("access_unavailable") from None

    def logout(self, credential: str):
        identifier, digest = credential_parts(credential, "qls")
        try:
            with self.engine.begin() as connection:
                connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
                connection.execute(
                    text(
                        "DELETE FROM operations.access_sessions "
                        "WHERE id=:id AND secret_digest=:digest"
                    ),
                    {"id": identifier, "digest": digest},
                )
        except SQLAlchemyError, OSError:
            raise AdmissionError("access_unavailable") from None

    def status(self, identity, policy):
        try:
            with self.engine.connect() as connection:
                token = valid_identity(
                    connection, identity, connection.scalar(text("SELECT clock_timestamp()"))
                )
                usage = (
                    connection.execute(
                        text("SELECT * FROM operations.access_usage WHERE token_id=:id"),
                        {"id": identity.token_id},
                    )
                    .mappings()
                    .one()
                )
                remaining = max(0, token["max_requests"] - usage["admitted_requests"])
                shared = (
                    connection.scalar(
                        text(
                            "SELECT charged_micro_usd FROM operations.demo_months "
                            "WHERE month=date_trunc('month',"
                            "clock_timestamp() AT TIME ZONE 'UTC')::date"
                        )
                    )
                    or 0
                )
                return {
                    "required": True,
                    "authenticated": True,
                    "name": token["name"],
                    "expires_at": token["expires_at"].isoformat(),
                    "remaining_requests": remaining,
                    "shared_available": shared < policy.monthly_micro_usd,
                    "budget_available": usage["charged_micro_usd"] < token["budget_micro_usd"],
                }
        except SQLAlchemyError, OSError:
            raise AdmissionError("access_unavailable") from None

    def audit(self, identity, request_id, result, duration_ms, http_status):
        from app.observability import count

        selected = {
            **summary(result),
            "duration_ms": count(duration_ms),
            "http_status": http_status,
        }
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO operations.access_requests "
                        "(request_id,token_id,created_at,completed_at,reserved_micro_usd,summary) "
                        "VALUES (:request,:token,clock_timestamp(),clock_timestamp(),"
                        "0,CAST(:summary AS jsonb)) "
                        "ON CONFLICT (request_id) DO UPDATE "
                        "SET completed_at=EXCLUDED.completed_at, "
                        "summary=access_requests.summary || EXCLUDED.summary "
                        "WHERE access_requests.token_id=EXCLUDED.token_id"
                    ),
                    {
                        "request": request_id,
                        "token": identity.token_id,
                        "summary": json.dumps(selected),
                    },
                )
            return True
        except SQLAlchemyError, OSError:
            return False
