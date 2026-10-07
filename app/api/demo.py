"""Expose the static time anchor without claiming that seed data is loaded."""

from fastapi import APIRouter

from app.demo import DATASET_VERSION, REFERENCE_DATE

router = APIRouter(tags=["demo"])


@router.get("/demo")
def demo_metadata() -> dict[str, str | bool]:
    return {
        "synthetic": True,
        "dataset_version": DATASET_VERSION,
        "reference_date": REFERENCE_DATE.isoformat(),
        "timezone": "UTC",
        "currency": "EUR",
    }
