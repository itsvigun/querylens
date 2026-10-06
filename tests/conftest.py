import pytest

from app.config import Settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    return Settings(_env_file=None, postgres_password="test-password", postgres_port=1)
