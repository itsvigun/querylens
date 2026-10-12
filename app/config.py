from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

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


class KnowledgeWriterSettings(Settings):
    postgres_user: Literal["querylens_knowledge_writer"] = Field(
        default="querylens_knowledge_writer", validation_alias="KNOWLEDGE_WRITER_USER"
    )
    postgres_password: SecretStr = Field(
        min_length=16, validation_alias="KNOWLEDGE_WRITER_PASSWORD"
    )


class KnowledgeReaderSettings(Settings):
    postgres_user: Literal["querylens_knowledge_ro"] = Field(
        default="querylens_knowledge_ro", validation_alias="KNOWLEDGE_READONLY_USER"
    )
    postgres_password: SecretStr = Field(
        min_length=16, validation_alias="KNOWLEDGE_READONLY_PASSWORD"
    )


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    embedding_provider: Literal["openai"] = "openai"
    embedding_model: Literal["text-embedding-3-small", "text-embedding-3-large"] = (
        "text-embedding-3-small"
    )
    embedding_dimensions: int = Field(default=1536, ge=1, le=3072)
    embedding_index_version: str = Field(default="v1", pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    knowledge_index_name: str = Field(default="default", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    openai_api_key: SecretStr | None = None
    embedding_timeout_seconds: float = Field(default=20, ge=1, le=30)

    @model_validator(mode="after")
    def valid_dimensions(self):
        if self.embedding_model == "text-embedding-3-small" and self.embedding_dimensions > 1536:
            raise ValueError("The small embedding model supports at most 1536 dimensions")
        return self


class LLMSettings(BaseSettings):
    """Separate from the embedding model and vector space configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    llm_model: Literal["gpt-5.4-mini"] = "gpt-5.4-mini"
    openai_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=20, ge=1, le=30)
    request_timeout_seconds: float = Field(default=60, ge=1, le=120)
    llm_max_calls: int = Field(default=6, ge=1, le=6)
    llm_max_tool_calls: int = Field(default=8, ge=1, le=8)
    llm_max_sql_calls: int = Field(default=3, ge=1, le=3)
    llm_max_sql_repairs: int = Field(default=2, ge=0, le=2)
    llm_max_input_bytes: int = Field(default=128000, ge=1000, le=128000)
    llm_max_output_tokens: int = Field(default=4000, ge=256, le=4000)


class PublicDemoSettings(BaseSettings):
    """No paid public traffic until an administrator configures the shared policy."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    public_demo_enabled: bool = False
    railway_environment_id: str | None = None
    public_chat_monthly_budget_usd: Decimal = Field(
        default=Decimal("0"), ge=0, le=100, decimal_places=6
    )
    public_chat_requests_per_minute: int = Field(default=6, ge=1, le=60)
    public_chat_max_concurrent: int = Field(default=1, ge=1, le=4)

    @model_validator(mode="after")
    def require_railway_controls(self):
        if self.railway_environment_id and not self.public_demo_enabled:
            raise ValueError("Railway requires public demo controls")
        return self


class DemoControlSettings(Settings):
    postgres_user: Literal["querylens_demo_control"] = Field(
        default="querylens_demo_control", validation_alias="DEMO_CONTROL_USER"
    )
    postgres_password: SecretStr = Field(min_length=16, validation_alias="DEMO_CONTROL_PASSWORD")


class AccessSettings(BaseSettings):
    """Invitation-only on Railway; local development can opt in explicitly."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    token_access_required: bool | None = None
    access_public_origin: str | None = None
    access_cookie_secure: bool = True
    access_session_ttl_seconds: int = Field(default=28800, ge=300, le=86400)
    railway_environment_id: str | None = None
    railway_public_domain: str | None = None

    @property
    def required(self) -> bool:
        return bool(self.railway_environment_id) or self.token_access_required is True

    @property
    def cookie_name(self) -> str:
        return "__Host-querylens_session" if self.access_cookie_secure else "querylens_dev_session"

    @model_validator(mode="after")
    def validate_access(self):
        if self.railway_environment_id and self.token_access_required is False:
            raise ValueError("Railway requires invitation access")
        if not self.required:
            return self
        if not self.access_public_origin and self.railway_public_domain:
            self.access_public_origin = "https://" + self.railway_public_domain
        origin = urlsplit(self.access_public_origin or "")
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path
            or origin.query
            or origin.fragment
        ):
            raise ValueError("Set an exact ACCESS_PUBLIC_ORIGIN without a path")
        if origin.scheme != "https" or not self.access_cookie_secure:
            if self.railway_environment_id or origin.hostname not in {"localhost", "127.0.0.1"}:
                raise ValueError("Hosted access requires HTTPS and secure cookies")
        return self
