"""Explicit live acceptance check; an ingested compatible index is required."""

import argparse
import json

from app.config import LLMSettings
from app.llm.service import ask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        required=True,
        help="Allow one paid question with bounded input/output usage",
    )
    parser.parse_args()
    settings = LLMSettings(llm_max_input_bytes=40000, llm_max_output_tokens=2000)
    result = ask("What was completed-order revenue in September, in EUR?", settings=settings)
    tools = {entry["tool"] for entry in result.get("trace", []) if entry["status"] == "ok"}
    values = [fact["value"] for fact in result.get("facts", [])]
    verified = (
        result["status"] == "answered"
        and tools == {"get_database_schema", "search_documentation", "execute_sql"}
        and "336080.07" in values
        and any(
            s["source_path"] == "knowledge/metrics.md" and "Revenue" in s["heading"]
            for s in result.get("sources", [])
        )
    )
    print(
        json.dumps(
            {"verified": verified, "verification_kind": "live_openai_responses", "result": result},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
