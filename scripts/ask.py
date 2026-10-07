"""Ask a business question using real OpenAI tool calls (paid API requests)."""

import argparse
import json

from app.llm.service import ask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    args = parser.parse_args()
    result = ask(args.question)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
