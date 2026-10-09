"""Shared, fail-closed public admission. Stored data contains no questions or secrets."""

import json
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import EmbeddingSettings, LLMSettings, PublicDemoSettings

# Standard, uncached USD per million tokens; reviewed 2026-10-09 against official
# model pages. No built-in paid tools, regional processing or alternate endpoints.
PRICING_VERSION = "openai-standard-2026-10-09"
CHAT_EMBEDDING_MAX_BYTES = 16000
LLM_INPUT_PRICE = Decimal("0.75")
LLM_OUTPUT_PRICE = Decimal("4.50")
EMBEDDING_PRICES = {
    "text-embedding-3-small": Decimal("0.02"),
    "text-embedding-3-large": Decimal("0.13"),
}
LOCK = 716202608


@dataclass(frozen=True)
class DemoPolicy:
    fingerprint: str
    monthly_micro_usd: int
    request_micro_usd: int
    requests_per_minute: int
    max_concurrent: int

    @classmethod
    def from_settings(
        cls, demo: PublicDemoSettings, llm: LLMSettings, embedding: EmbeddingSettings
    ):
        # UTF-8 byte BPE bound plus the provider's per-call protocol allowance.
        # Unknown usage/crashes never reclaim an admitted reservation. This is a
        # conservative local allocation, not a provider invoice/account spend cap.
        request = int(
            (
                llm.llm_max_input_bytes * LLM_INPUT_PRICE
                + llm.llm_max_output_tokens * LLM_OUTPUT_PRICE
                + CHAT_EMBEDDING_MAX_BYTES * EMBEDDING_PRICES[embedding.embedding_model]
            ).to_integral_value(rounding=ROUND_CEILING)
        )
        monthly = int(demo.public_chat_monthly_budget_usd * 1_000_000)
        identity = {
            "pricing": PRICING_VERSION,
            "llm": llm.model_dump(exclude={"openai_api_key"}),
            "embedding_model": embedding.embedding_model,
            "monthly_micro_usd": monthly,
            "request_micro_usd": request,
            "rate": demo.public_chat_requests_per_minute,
            "concurrency": demo.public_chat_max_concurrent,
        }
        digest = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return cls(
            digest,
            monthly,
            request,
            demo.public_chat_requests_per_minute,
            demo.public_chat_max_concurrent,
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

    def admit(self, request_id: str):
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
                if (
                    state.charged_micro_usd + self.policy.request_micro_usd
                    > self.policy.monthly_micro_usd
                ):
                    raise AdmissionError("demo_budget_exhausted", 429)
                connection.execute(
                    text(
                        "UPDATE operations.demo_months "
                        "SET charged_micro_usd=charged_micro_usd+:charge, "
                        "rate_minute=:minute, rate_count=:count WHERE month=:month"
                    ),
                    {
                        "charge": self.policy.request_micro_usd,
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

    def release(self, request_id: str):
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM operations.demo_leases WHERE request_id=:id"),
                    {"id": request_id},
                )
        except SQLAlchemyError, OSError:
            # Leave the durable lease and charge in place, requiring admin recovery.
            raise AdmissionError("demo_controls_unavailable") from None
