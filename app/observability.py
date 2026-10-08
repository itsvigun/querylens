"""Allowlisted JSON summaries: never log questions, SQL, sources or exceptions."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

from app.llm.workflow import REPAIRABLE_SQL_ERRORS, SAFE_PROVIDER_ERRORS, TERMINAL_TOOL_ERRORS

REQUEST_ID: ContextVar[str | None] = ContextVar("querylens_request_id", default=None)
ERRORS = (
    SAFE_PROVIDER_ERRORS
    | TERMINAL_TOOL_ERRORS
    | REPAIRABLE_SQL_ERRORS
    | {
        "configuration_error",
        "invalid_input",
        "sql_retry_budget_exhausted",
        "tool_budget_exhausted",
        "duplicate_call_id",
        "workflow_step_limit",
        "busy",
        "invalid_request",
        "request_failed",
    }
)
STATUSES = {"answered", "clarification", "insufficient_context", "unsupported", "error"}
LOGGER = logging.getLogger("querylens.analytics")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


def count(value):
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


def summary(result: dict) -> dict:
    """Copy only fixed identifiers, bounded counts and true booleans."""
    usage = result.get("usage") or {}
    embedding = result.get("embedding_usage") or {}
    workflow = result.get("workflow") or {}
    category = (result.get("error") or {}).get("category")
    return {
        "status": result.get("status") if result.get("status") in STATUSES else "error",
        "error_category": category
        if category in ERRORS
        else ("request_failed" if category else None),
        "provider": "openai",
        "model": "gpt-5.4-mini" if usage.get("model") == "gpt-5.4-mini" else None,
        "llm_requests": count(usage.get("requests")),
        "input_tokens": count(usage.get("input_tokens")),
        "output_tokens": count(usage.get("output_tokens")),
        "usage_complete": usage.get("usage_complete") is True,
        "tool_calls": count(workflow.get("tool_calls")),
        "sql_attempts": count(workflow.get("sql_attempts")),
        "sql_repairs": count(workflow.get("sql_repairs")),
        "embedding_model": embedding.get("model")
        if embedding.get("model") in {"text-embedding-3-small", "text-embedding-3-large"}
        else None,
        "embedding_requests": count(embedding.get("requests")),
        "embedding_tokens": count(embedding.get("prompt_tokens")),
    }


def log_request(request_id: str, result: dict, duration_ms: int, *, http_status=None):
    event = {
        "event": "analytics_request",
        "timestamp": datetime.now(UTC).isoformat(),
        "request_id": request_id,
        "duration_ms": count(duration_ms),
        "http_status": http_status,
        **summary(result),
    }
    LOGGER.info(json.dumps(event, separators=(",", ":"), allow_nan=False))
