"""Shared, fail-closed public admission. Stored data contains no questions or secrets."""

import json
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import EmbeddingSettings, LLMSettings, PublicDemoSettings
from app.costs import PRICING_VERSION, usage_cost_micro_usd

LOCK = 716202608


@dataclass(frozen=True)
class DemoPolicy:
    fingerprint: str
    monthly_micro_usd: int
    requests_per_minute: int
    max_concurrent: int
    embedding_model: str

    @classmethod
    def from_settings(
        cls, demo: PublicDemoSettings, llm: LLMSettings, embedding: EmbeddingSettings
    ):
        monthly = int(demo.public_chat_monthly_budget_usd * 1_000_000)
        identity = {
            "accounting": "invitation-post-request-usage-v1",
            "pricing": PRICING_VERSION,
            "llm": llm.model_dump(exclude={"openai_api_key"}),
            "embedding_model": embedding.embedding_model,
            "monthly_micro_usd": monthly,
            "rate": demo.public_chat_requests_per_minute,
            "concurrency": demo.public_chat_max_concurrent,
        }
        digest = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return cls(
            digest,
            monthly,
            demo.public_chat_requests_per_minute,
            demo.public_chat_max_concurrent,
            embedding.embedding_model,
        )


class AdmissionError(ValueError):
    def __init__(self, category: str, status_code: int = 503, retry_after: int | None = None):
        self.category = category
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(category)


class DemoGate:
    def __init__(self, engine: Engine, policy: DemoPolicy):
        self.engine = engine
        self.policy = policy

    def admit(self, request_id: str, *, identity=None):
        UUID(request_id)
        try:
            with self.engine.begin() as connection:
                connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
                fingerprint = connection.scalar(
                    text("SELECT fingerprint FROM operations.demo_policy WHERE id=1")
                )
                if fingerprint != self.policy.fingerprint:
                    raise AdmissionError("demo_policy_mismatch")
                now = connection.scalar(text("SELECT clock_timestamp()"))
                month = now.date().replace(day=1)
                minute = now.replace(second=0, microsecond=0)
                if identity is not None:
                    from app.access import admit_access

                    admit_access(connection, identity, request_id, now, PRICING_VERSION)
                connection.execute(
                    text(
                        "INSERT INTO operations.demo_months "
                        "(month, charged_micro_usd, rate_minute, rate_count) "
                        "VALUES (:month, 0, :minute, 0) ON CONFLICT (month) DO NOTHING"
                    ),
                    {"month": month, "minute": minute},
                )
                state = connection.execute(
                    text(
                        "SELECT charged_micro_usd, rate_minute, rate_count "
                        "FROM operations.demo_months WHERE month=:month"
                    ),
                    {"month": month},
                ).one()
                count = state.rate_count if state.rate_minute == minute else 0
                if count >= self.policy.requests_per_minute:
                    raise AdmissionError("demo_rate_limit", 429, 60 - now.second)
                if (
                    connection.scalar(text("SELECT count(*) FROM operations.demo_leases"))
                    >= self.policy.max_concurrent
                ):
                    raise AdmissionError("demo_busy", 429, 5)
                if state.charged_micro_usd >= self.policy.monthly_micro_usd:
                    raise AdmissionError("demo_budget_exhausted", 429)
                connection.execute(
                    text(
                        "UPDATE operations.demo_months "
                        "SET rate_minute=:minute, rate_count=:count WHERE month=:month"
                    ),
                    {
                        "minute": minute,
                        "count": count + 1,
                        "month": month,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO operations.demo_leases(request_id, admitted_at, month) "
                        "VALUES (:id, :now, :month)"
                    ),
                    {"id": request_id, "now": now, "month": month},
                )
        except SQLAlchemyError, OSError:
            raise AdmissionError("demo_controls_unavailable") from None

    def release(self, request_id: str, *, result=None):
        """Record complete usage once, then release concurrency; never reserve money."""
        try:
            with self.engine.begin() as connection:
                connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
                lease = connection.execute(
                    text("SELECT month FROM operations.demo_leases WHERE request_id=:id"),
                    {"id": request_id},
                ).one_or_none()
                if lease is None:
                    return  # Repeated completion cannot count usage twice.
                quote = usage_cost_micro_usd(result)
                known = (
                    quote is not None
                    and result["embedding_usage"]["model"] == self.policy.embedding_model
                )
                connection.execute(
                    text(
                        "UPDATE operations.demo_months SET "
                        "charged_micro_usd=charged_micro_usd+:cost, "
                        "unknown_requests=unknown_requests+:unknown WHERE month=:month"
                    ),
                    {
                        "cost": quote if known else 0,
                        "unknown": int(not known),
                        "month": lease.month,
                    },
                )
                record = connection.execute(
                    text(
                        "SELECT token_id,usage_state FROM "
                        "operations.access_requests WHERE request_id=:id"
                    ),
                    {"id": request_id},
                ).one_or_none()
                if record is not None and record.usage_state == "pending":
                    connection.execute(
                        text(
                            "UPDATE operations.access_usage SET "
                            "charged_micro_usd=charged_micro_usd+:cost, "
                            "unknown_requests=unknown_requests+:unknown WHERE token_id=:id"
                        ),
                        {
                            "cost": quote if known else 0,
                            "unknown": int(not known),
                            "id": record.token_id,
                        },
                    )
                    receipt = {"usage_complete": known}
                    if known:
                        receipt.update(
                            model="gpt-5.4-mini",
                            input_tokens=result["usage"]["input_tokens"],
                            output_tokens=result["usage"]["output_tokens"],
                            embedding_model=self.policy.embedding_model,
                            embedding_tokens=result["embedding_usage"]["prompt_tokens"],
                        )
                    connection.execute(
                        text(
                            "UPDATE operations.access_requests SET charged_micro_usd=:cost, "
                            "summary=summary || CAST(:billing AS jsonb), "
                            "usage_state=:state WHERE request_id=:id"
                        ),
                        {
                            "cost": quote if known else None,
                            "state": "recorded" if known else "unknown",
                            "id": request_id,
                            "billing": json.dumps({"billing_usage": receipt}),
                        },
                    )
                connection.execute(
                    text("DELETE FROM operations.demo_leases WHERE request_id=:id"),
                    {"id": request_id},
                )
        except SQLAlchemyError, OSError:
            # Roll back usage and retain the lease for explicit owner recovery.
            raise AdmissionError("demo_controls_unavailable") from None
