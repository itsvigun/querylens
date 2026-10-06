import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.db.connection import create_database_engine
from app.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("QUERYLENS_INTEGRATION") != "1",
        reason="Set QUERYLENS_INTEGRATION=1 with a migrated local PostgreSQL database",
    ),
]


def test_migrated_postgres_is_ready_and_vector_operations_work() -> None:
    settings = Settings()
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200, response.json()
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            distance = connection.scalar(text("SELECT '[1,2,3]'::vector <-> '[1,2,3]'::vector"))
            timezone = connection.scalar(text("SHOW timezone"))
        assert distance == 0
        assert timezone == "UTC"
    finally:
        engine.dispose()
