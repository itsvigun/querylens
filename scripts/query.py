"""Local smoke interface for schema metadata and the bounded database tool."""

import argparse
import json
import sys

from pydantic import ValidationError

from app.tools.database import DatabaseTools
from app.tools.schema import get_database_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", action="store_true", help="Show the reviewed analytics schema")
    args = parser.parse_args()
    if args.schema:
        print(json.dumps(get_database_schema(), indent=2))
        return 0
    # Bounded stdin keeps shell quoting and credentials out of the query interface.
    query = sys.stdin.buffer.read(16385)
    try:
        query = query.decode("utf-8")
        with DatabaseTools() as tools:
            result = tools.execute_sql(query)
    except ValidationError, ValueError:
        print(
            "SQL tool initialization failed. Check dedicated reader configuration.", file=sys.stderr
        )
        return 1
    print(result.json_bytes().decode("utf-8"))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
