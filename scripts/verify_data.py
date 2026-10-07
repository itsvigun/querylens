"""Compare executed control SQL with checked-in, independently calculated values."""

import json
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import Connection, create_engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import AnalyticsSettings
from app.db.schema import ANALYTICS_TABLES
from app.demo import DATASET_VERSION, REFERENCE_DATE
from scripts.reference_metrics import PERIODS, normalize_metrics
from scripts.seed import database_fingerprint

SCRIPT_ROOT = Path(__file__).resolve().parent


def control_query(name: str):
    return text((SCRIPT_ROOT / "sql" / f"{name}.sql").read_text())


def query_report(connection: Connection) -> dict:
    report = {
        "dataset_version": DATASET_VERSION,
        "reference_date": REFERENCE_DATE.isoformat(),
        "sha256": database_fingerprint(connection),
        "counts": {},
        "periods": {},
    }
    for table in ANALYTICS_TABLES:
        report["counts"][table.name] = connection.scalar(select(func.count()).select_from(table))
    for name, (start, end) in PERIODS.items():
        row = connection.execute(control_query("period_metrics"), {"start": start, "end": end})
        report["periods"][name] = normalize_metrics(dict(row.mappings().one()))
    report["country_revenue"] = {}
    for name in ("august", "september"):
        start, end = PERIODS[name]
        rows = connection.execute(control_query("country_revenue"), {"start": start, "end": end})
        report["country_revenue"][name] = [normalize_metrics(dict(r)) for r in rows.mappings()]
    start, end = PERIODS["september"]
    rows = connection.execute(control_query("subscription_churn"), {"start": start, "end": end})
    report["september_churn"] = [normalize_metrics(dict(row)) for row in rows.mappings()]
    report["conversion"] = {}
    for name in ("august", "september", "empty_june"):
        start, end = PERIODS[name]
        row = connection.execute(
            control_query("cohort_conversion"),
            {"start": start, "end": end, "reference_date": REFERENCE_DATE},
        )
        report["conversion"][name] = normalize_metrics(dict(row.mappings().one()))
    return report


def expected_report() -> dict:
    return json.loads((SCRIPT_ROOT / "reference_values.json").read_text())


def main() -> int:
    engine = None
    try:
        settings = AnalyticsSettings()
        engine = create_engine(
            settings.database_url, connect_args=settings.database_connect_args, hide_parameters=True
        )
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            actual = query_report(connection)
        if actual != expected_report():
            print(
                "Data verification failed: dataset or control metrics differ from reference.",
                file=sys.stderr,
            )
            return 1
    except SQLAlchemyError, ValidationError, ValueError:
        print(
            "Data verification failed. Check read-only credentials, migrations, and seed.",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps({"status": "verified", **actual}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
