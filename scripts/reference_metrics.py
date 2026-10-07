"""Independent Python oracle for trusted control SQL, not an LLM evaluation."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.demo import DATASET_VERSION, REFERENCE_DATE
from scripts.seed import dataset_fingerprint

PERIODS = {
    "july": (datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC)),
    "august": (datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC)),
    "september": (datetime(2026, 9, 1, tzinfo=UTC), REFERENCE_DATE),
    "last_week": (datetime(2026, 9, 21, tzinfo=UTC), datetime(2026, 9, 28, tzinfo=UTC)),
    "empty_june": (datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)),
}


def ratio(numerator: Decimal | int, denominator: int) -> Decimal | None:
    return Decimal(numerator) / denominator if denominator else None


def normalize_metrics(row: dict) -> dict:
    """Represent money exactly; compare ratios rounded to eight decimal places."""
    return {
        key: (format(value, ".2f") if key == "revenue" else format(value, ".8f"))
        if isinstance(value, Decimal)
        else value
        for key, value in row.items()
    }


def reference_report(dataset: dict[str, list[dict]]) -> dict:
    user_by_id = {user["id"]: user for user in dataset["users"]}
    report = {
        "dataset_version": DATASET_VERSION,
        "reference_date": REFERENCE_DATE.isoformat(),
        "sha256": dataset_fingerprint(dataset),
        "counts": {name: len(rows) for name, rows in dataset.items()},
        "periods": {},
    }
    for name, (start, end) in PERIODS.items():
        completed = [
            o
            for o in dataset["orders"]
            if o["status"] == "completed" and start <= o["created_at"] < end
        ]
        revenue = sum((o["amount"] for o in completed), Decimal(0))
        payers = {o["user_id"] for o in completed}
        active = {
            e["user_id"]
            for e in dataset["events"]
            if e["event_type"] == "session" and start <= e["created_at"] < end
        }
        report["periods"][name] = normalize_metrics(
            {
                "revenue": revenue,
                "completed_orders": len(completed),
                "paying_users": len(payers),
                "active_users": len(active),
                "arpu": ratio(revenue, len(active)),
                "arppu": ratio(revenue, len(payers)),
            }
        )
    report["country_revenue"] = {}
    for name in ("august", "september"):
        start, end = PERIODS[name]
        groups = {}
        for order in dataset["orders"]:
            if order["status"] == "completed" and start <= order["created_at"] < end:
                country = user_by_id[order["user_id"]]["country"]
                group = groups.setdefault(
                    country, {"country": country, "completed_orders": 0, "revenue": Decimal(0)}
                )
                group["completed_orders"] += 1
                group["revenue"] += order["amount"]
        report["country_revenue"][name] = [normalize_metrics(groups[c]) for c in sorted(groups)]
    start, end = PERIODS["september"]
    groups = {}
    for subscription in dataset["subscriptions"]:
        cancelled = subscription["cancelled_at"]
        if subscription["started_at"] < start and (cancelled is None or cancelled >= start):
            group = groups.setdefault(
                subscription["plan"],
                {"plan": subscription["plan"], "subscriptions_at_start": 0, "cancellations": 0},
            )
            group["subscriptions_at_start"] += 1
            group["cancellations"] += int(cancelled is not None and start <= cancelled < end)
    report["september_churn"] = [
        normalize_metrics(
            {
                **groups[plan],
                "churn_rate": ratio(
                    groups[plan]["cancellations"], groups[plan]["subscriptions_at_start"]
                ),
            }
        )
        for plan in sorted(groups)
    ]
    orders_by_user = {}
    for order in dataset["orders"]:
        if order["status"] == "completed":
            orders_by_user.setdefault(order["user_id"], []).append(order["created_at"])
    report["conversion"] = {}
    for name in ("august", "september", "empty_june"):
        start, end = PERIODS[name]
        cohort = [u for u in dataset["users"] if start <= u["registered_at"] < end]
        observed = [u for u in cohort if u["registered_at"] + timedelta(days=30) <= REFERENCE_DATE]
        converted = sum(
            any(
                u["registered_at"] <= timestamp < u["registered_at"] + timedelta(days=30)
                for timestamp in orders_by_user.get(u["id"], [])
            )
            for u in observed
        )
        fully_observed = len(observed) == len(cohort) if cohort else None
        report["conversion"][name] = normalize_metrics(
            {
                "cohort_users": len(cohort),
                "converted_users": converted,
                "fully_observed": fully_observed,
                "conversion_rate": ratio(converted, len(cohort)) if fully_observed else None,
            }
        )
    return report
