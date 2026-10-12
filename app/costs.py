"""Conservative usage quotes in integer micro-USD, independent of provider invoices."""

from decimal import ROUND_CEILING, Decimal

# Standard uncached micro-USD per token; official model prices reviewed 2026-10-12.
# This estimate ignores cached discounts and is not a provider invoice.
PRICING_VERSION = "openai-standard-2026-10-09"
LLM_INPUT_PRICE = Decimal("0.75")
LLM_OUTPUT_PRICE = Decimal("4.50")
EMBEDDING_PRICES = {
    "text-embedding-3-small": Decimal("0.02"),
    "text-embedding-3-large": Decimal("0.13"),
}


def usage_cost_micro_usd(result):
    if not isinstance(result, dict):
        return None
    llm, embedding = result.get("usage"), result.get("embedding_usage")
    if not isinstance(llm, dict) or not isinstance(embedding, dict):
        return None
    if llm.get("usage_complete") is not True or embedding.get("usage_complete") is not True:
        return None
    values = [
        llm.get("requests"),
        llm.get("input_tokens"),
        llm.get("output_tokens"),
        embedding.get("requests"),
        embedding.get("prompt_tokens"),
    ]
    if any(type(value) is not int or not 0 <= value <= 1_000_000_000 for value in values):
        return None
    calls, inputs, outputs, embedding_calls, tokens = values
    if (
        llm.get("model") != "gpt-5.4-mini"
        or not isinstance(embedding.get("model"), str)
        or embedding["model"] not in EMBEDDING_PRICES
    ):
        return None
    if (calls == 0 and (inputs or outputs)) or (embedding_calls == 0 and tokens):
        return None
    if (calls > 0 and inputs == 0) or (embedding_calls > 0 and tokens == 0):
        return None
    # Ignore cached discounts: a quote may exceed the bill, never infer free usage.
    amount = (
        Decimal(inputs) * LLM_INPUT_PRICE
        + Decimal(outputs) * LLM_OUTPUT_PRICE
        + Decimal(tokens) * EMBEDDING_PRICES[embedding["model"]]
    )
    return int(amount.to_integral_value(rounding=ROUND_CEILING))
