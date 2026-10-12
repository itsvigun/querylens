"""Usage-based quotes fail closed on partial or malformed provider accounting."""

import copy

import pytest

from app.costs import usage_cost_micro_usd


def reported_usage():
    return {
        "usage": {
            "model": "gpt-5.4-mini",
            "requests": 3,
            "input_tokens": 7232,
            "output_tokens": 439,
            "usage_complete": True,
        },
        "embedding_usage": {
            "model": "text-embedding-3-small",
            "requests": 1,
            "prompt_tokens": 11,
            "usage_complete": True,
        },
    }


def test_usage_quote_rounds_up_in_micro_usd_and_ignores_cache_discounts():
    result = reported_usage()
    result["usage"]["cached_tokens"] = 7000
    assert usage_cost_micro_usd(result) == 7400
    # Semantic answer failure does not erase already known provider consumption.
    result.update(status="error", error={"category": "ungrounded_answer"})
    assert usage_cost_micro_usd(result) == 7400


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("usage", "usage_complete", False),
        ("embedding_usage", "usage_complete", None),
        ("usage", "input_tokens", -1),
        ("usage", "input_tokens", True),
        ("usage", "output_tokens", "439"),
        ("usage", "model", "unknown-model"),
        ("embedding_usage", "model", "unknown-model"),
        ("embedding_usage", "prompt_tokens", 1_000_000_001),
        ("usage", "requests", 0),
        ("embedding_usage", "requests", 0),
    ],
)
def test_incomplete_or_inconsistent_usage_has_no_cost_estimate(section, key, value):
    result = copy.deepcopy(reported_usage())
    result[section][key] = value
    assert usage_cost_micro_usd(result) is None


def test_missing_usage_is_unknown_and_zero_calls_with_zero_usage_are_valid():
    assert usage_cost_micro_usd({"status": "error"}) is None
    result = reported_usage()
    result["usage"].update(requests=0, input_tokens=0, output_tokens=0)
    result["embedding_usage"].update(requests=0, prompt_tokens=0)
    assert usage_cost_micro_usd(result) == 0


def test_malformed_model_and_zero_reported_tokens_for_an_attempt_are_unknown():
    result = reported_usage()
    result["embedding_usage"]["model"] = {"untrusted": "text"}
    assert usage_cost_micro_usd(result) is None
    result = reported_usage()
    result["usage"]["input_tokens"] = 0
    assert usage_cost_micro_usd(result) is None
