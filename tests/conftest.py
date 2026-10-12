import pytest

from app.config import AccessSettings, PublicDemoSettings, Settings


@pytest.fixture(autouse=True)
def isolated_http_policy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer's protected .env must not change explicitly configured test apps.
    for model in (AccessSettings, PublicDemoSettings):
        monkeypatch.setitem(model.model_config, "env_file", None)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    return Settings(_env_file=None, postgres_password="test-password", postgres_port=1)
