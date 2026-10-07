"""Generate and load a deterministic synthetic dataset as an explicit command."""

import argparse
import hashlib
import json
import random
import sys
from bisect import bisect_right
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.db.connection import create_database_engine, database_checks, migration_heads
from app.db.schema import ANALYTICS_TABLES
from app.demo import DATASET_VERSION, RANDOM_SEED, REFERENCE_DATE

COUNTRIES = ("DE", "PL", "FR", "ES")
PLANS = ("basic", "pro", "enterprise")
MONTH_COUNTS = (
    (7, (2000, 1700, 1700, 1600)),
    (8, (2500, 1800, 1700, 1500)),
    (9, (700, 1800, 1600, 1400)),
)


def generate_dataset() -> dict[str, list[dict]]:
    rng = random.Random(RANDOM_SEED)
    start = datetime(2026, 7, 1, tzinfo=UTC)
    span = int((REFERENCE_DATE - start).total_seconds())
    users = []
    for index in range(10000):
        registered_at = start if index < 400 else start + timedelta(seconds=rng.randrange(span))
        users.append(
            {
                "id": index + 1,
                "country": COUNTRIES[index % 4],
                "registered_at": registered_at,
                "status": "disabled" if index % 20 == 0 else "active",
            }
        )
    by_country = {
        country: sorted(
            (u for u in users if u["country"] == country), key=lambda u: u["registered_at"]
        )
        for country in COUNTRIES
    }
    registration_dates = {
        country: [u["registered_at"] for u in rows] for country, rows in by_country.items()
    }
    orders = []
    for month, counts in MONTH_COUNTS:
        month_start = datetime(2026, month, 1, tzinfo=UTC)
        month_end = datetime(2026, month + 1, 1, tzinfo=UTC)
        month_seconds = int((month_end - month_start).total_seconds())
        for country, count in zip(COUNTRIES, counts, strict=True):
            for index in range(count):
                created_at = month_start + timedelta(seconds=rng.randrange(month_seconds))
                eligible = bisect_right(registration_dates[country], created_at)
                user = by_country[country][rng.randrange(eligible)]
                status = (
                    "completed"
                    if index % 10 < 8
                    else ("refunded" if index % 10 == 8 else "cancelled")
                )
                orders.append(
                    {
                        "id": len(orders) + 1,
                        "user_id": user["id"],
                        "amount": Decimal(rng.randrange(500, 15001)) / Decimal(100),
                        "currency": "EUR",
                        "created_at": created_at,
                        "status": status,
                    }
                )
    # All purchases have a session; extra session/checkout events broaden activity.
    events = [
        {
            "id": u["id"],
            "user_id": u["id"],
            "event_type": "session",
            "created_at": u["registered_at"],
        }
        for u in users
    ]
    for order in orders:
        events.append(
            {
                "id": len(events) + 1,
                "user_id": order["user_id"],
                "event_type": "session",
                "created_at": order["created_at"],
            }
        )
    for index in range(50000):
        user = users[rng.randrange(len(users))]
        seconds = int((REFERENCE_DATE - user["registered_at"]).total_seconds())
        events.append(
            {
                "id": len(events) + 1,
                "user_id": user["id"],
                "event_type": "checkout" if index % 5 == 0 else "session",
                "created_at": user["registered_at"] + timedelta(seconds=rng.randrange(seconds)),
            }
        )
    eligible_subscribers = [
        u for u in users if u["registered_at"] < datetime(2026, 8, 1, tzinfo=UTC)
    ]
    subscribers = rng.sample(eligible_subscribers, 3000)
    subscriptions = []
    september_cancellations = {"basic": 190, "pro": 95, "enterprise": 38}
    for index, user in enumerate(subscribers):
        plan = PLANS[index % 3]
        plan_index = index // 3
        started_at = min(
            user["registered_at"] + timedelta(hours=1),
            datetime(2026, 8, 1, tzinfo=UTC) - timedelta(seconds=1),
        )
        cancelled_at = None
        if plan_index < 50:
            cancelled_at = datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=plan_index % 31)
        elif plan_index < 50 + september_cancellations[plan]:
            cancelled_at = datetime(2026, 9, 1, tzinfo=UTC) + timedelta(days=(plan_index - 50) % 30)
        subscriptions.append(
            {
                "id": index + 1,
                "user_id": user["id"],
                "plan": plan,
                "started_at": started_at,
                "cancelled_at": cancelled_at,
            }
        )
    return {"users": users, "orders": orders, "events": events, "subscriptions": subscriptions}


def fingerprint_rows(digest, table_name: str, rows: Iterable[Mapping]) -> None:
    digest.update((table_name + "\n").encode())
    for row in rows:
        values = dict(row)
        for key, value in values.items():
            if isinstance(value, datetime):
                values[key] = value.astimezone(UTC).isoformat()
            elif isinstance(value, Decimal):
                values[key] = format(value, ".2f")
        digest.update((json.dumps(values, sort_keys=True, separators=(",", ":")) + "\n").encode())


def dataset_fingerprint(dataset: dict[str, list[dict]]) -> str:
    digest = hashlib.sha256()
    for table in ANALYTICS_TABLES:
        fingerprint_rows(digest, table.name, dataset[table.name])
    return digest.hexdigest()


def database_fingerprint(connection: Connection) -> str:
    digest = hashlib.sha256()
    for table in ANALYTICS_TABLES:
        rows = connection.execute(select(table).order_by(table.c.id)).mappings()
        fingerprint_rows(digest, table.name, rows)
    return digest.hexdigest()


def load_dataset(engine: Engine, dataset: dict[str, list[dict]], *, replace: bool = False) -> str:
    if not all(database_checks(engine, migration_heads()).values()):
        raise ValueError("Run migrations before seeding")
    expected = dataset_fingerprint(dataset)
    with engine.begin() as connection:
        # Serialize seed commands and prevent concurrent changes during comparison/load.
        connection.execute(text("SELECT pg_advisory_xact_lock(716202602)"))
        connection.execute(
            text(
                "LOCK TABLE analytics.users, analytics.orders, analytics.events, "
                "analytics.subscriptions IN SHARE ROW EXCLUSIVE MODE"
            )
        )
        populated = any(
            connection.scalar(select(table.c.id).limit(1)) for table in ANALYTICS_TABLES
        )
        if populated:
            if database_fingerprint(connection) == expected:
                return "unchanged"
            if not replace:
                raise ValueError("Existing analytics differs; use --replace only for this demo")
            for table in reversed(ANALYTICS_TABLES):
                connection.execute(table.delete())
        for table in ANALYTICS_TABLES:
            rows = dataset[table.name]
            for offset in range(0, len(rows), 2000):
                connection.execute(table.insert(), rows[offset : offset + 2000])
        if database_fingerprint(connection) != expected:
            raise ValueError("Loaded dataset fingerprint does not match")
    return "loaded"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace differing synthetic analytics data, in one transaction",
    )
    args = parser.parse_args()
    engine = None
    try:
        dataset = generate_dataset()
        engine = create_database_engine(Settings())
        status = load_dataset(engine, dataset, replace=args.replace)
    except SQLAlchemyError, ValidationError, ValueError:
        print(
            "Seed failed. Check migrations/configuration; differing data requires --replace.",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    print(
        json.dumps(
            {
                "status": status,
                "dataset_version": DATASET_VERSION,
                "reference_date": REFERENCE_DATE.isoformat(),
                "random_seed": RANDOM_SEED,
                "counts": {name: len(rows) for name, rows in dataset.items()},
                "sha256": dataset_fingerprint(dataset),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
