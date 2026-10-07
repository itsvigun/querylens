from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_user: str = Field(default="querylens", min_length=1)
    postgres_password: SecretStr = Field(min_length=1)
    postgres_db: str = Field(default="querylens", min_length=1)
    postgres_host: str = Field(default="127.0.0.1", min_length=1)
    postgres_port: int = Field(default=5433, ge=1, le=65535)
    db_connect_timeout_seconds: int = Field(default=3, ge=1, le=30)
    db_statement_timeout_ms: int = Field(default=5000, ge=1, le=60000)

    @property
    def database_url(self) -> URL:
        # URL.create handles reserved characters in passwords without string interpolation.
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def database_connect_args(self) -> dict[str, str | int]:
        return {
            "connect_timeout": self.db_connect_timeout_seconds,
            "options": (
                f"-c statement_timeout={self.db_statement_timeout_ms} "
                "-c lock_timeout=1000 -c timezone=UTC"
            ),
        }


class AnalyticsSettings(Settings):
    """Dedicated reader credentials; never fall back to the owner password."""

    postgres_user: Literal["querylens_analytics_ro"] = Field(
        default="querylens_analytics_ro", validation_alias="ANALYTICS_READONLY_USER"
    )
    postgres_password: SecretStr = Field(
        min_length=16, validation_alias="ANALYTICS_READONLY_PASSWORD"
    )


class SQLToolLimits(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sql_max_rows: int = Field(default=1000, ge=1, le=1000)
    sql_max_result_bytes: int = Field(default=65536, ge=1024, le=1048576)
    sql_statement_timeout_ms: int = Field(default=5000, ge=10, le=10000)
    sql_tool_timeout_ms: int = Field(default=10000, ge=100, le=30000)
