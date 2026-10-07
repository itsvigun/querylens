import random

from app.demo import REFERENCE_DATE
from scripts.reference_metrics import reference_report
from scripts.seed import dataset_fingerprint, generate_dataset
from scripts.verify_data import expected_report


def test_seed_matches_versioned_reference_and_is_independent_of_global_random() -> None:
    dataset = generate_dataset()
    assert reference_report(dataset) == expected_report()
    random.seed(1)
    assert dataset_fingerprint(generate_dataset()) == expected_report()["sha256"]


def test_synthetic_rows_have_valid_relationships_money_and_utc_dates() -> None:
    dataset = generate_dataset()
    users = {u["id"]: u for u in dataset["users"]}
    for name, rows in dataset.items():
        assert len({row["id"] for row in rows}) == len(rows)
        for row in rows:
            if name != "users":
                assert row["user_id"] in users
                timestamp = row.get("created_at", row.get("started_at"))
                assert timestamp >= users[row["user_id"]]["registered_at"]
            for key in ("registered_at", "created_at", "started_at", "cancelled_at"):
                value = row.get(key)
                if value is not None:
                    assert value.utcoffset().total_seconds() == 0
                    assert value < REFERENCE_DATE
    for order in dataset["orders"]:
        assert order["currency"] == "EUR"
        assert order["amount"] >= 0
        assert order["amount"] == order["amount"].quantize(type(order["amount"])("0.01"))
    assert {order["status"] for order in dataset["orders"]} == {
        "completed",
        "refunded",
        "cancelled",
    }
