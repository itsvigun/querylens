from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_demo_metadata_is_visible_without_a_database(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/demo")
    assert response.status_code == 200
    assert response.json() == {
        "synthetic": True,
        "dataset_version": "synthetic-v1",
        "reference_date": "2026-10-01T00:00:00+00:00",
        "timezone": "UTC",
        "currency": "EUR",
    }
