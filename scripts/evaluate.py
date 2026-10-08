"""Run synthetic evaluations; live mode requires explicit total byte/token budgets."""

import argparse
import json
import sys
from pathlib import Path

from evals.runner import load_cases, run_evaluation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--offline",
        action="store_true",
        help="Real PostgreSQL, scripted calls and stub vectors; no API key",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="Paid OpenAI calls, no ingestion; requires compatible default index",
    )
    parser.add_argument("--cases", nargs="+", help="Select checked-in case IDs")
    parser.add_argument("--max-input-bytes", type=int)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--max-embedding-input-bytes", type=int)
    parser.add_argument(
        "--output", type=Path, help="Write a JSON report; parent directory must exist"
    )
    args = parser.parse_args(argv)
    suite = load_cases()
    cases = suite["cases"]
    if args.cases:
        if len(args.cases) != len(set(args.cases)) or set(args.cases) - {c["id"] for c in cases}:
            parser.error("Select unique, known case IDs.")
        cases = [c for c in cases if c["id"] in args.cases]
    elif args.live:
        cases = [c for c in cases if c["live_eligible"]]
    budgets = (args.max_input_bytes, args.max_output_tokens, args.max_embedding_input_bytes)
    if args.live and (
        any(v is None or v < 1 for v in budgets) or any(not c["live_eligible"] for c in cases)
    ):
        parser.error(
            "Live mode requires positive input/output/embedding budgets and live-eligible cases."
        )
    if args.offline and any(v is not None for v in budgets):
        parser.error("Provider budgets apply only to --live.")
    # Check the output destination before spending anything.
    if args.output and (not args.output.parent.is_dir() or args.output.exists()):
        parser.error("Report parent directory must exist and the file must be new.")
    try:
        report = run_evaluation(
            cases,
            live=args.live,
            input_bytes=budgets[0],
            output_tokens=budgets[1],
            embedding_bytes=budgets[2],
        )
        rendered = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x") as stream:
                stream.write(rendered)
        print(rendered, end="")
        return 1 if report["failed"] else 0
    except Exception:
        print(
            "Evaluation failed. Check the dedicated database, seed, roles, index and budgets.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
