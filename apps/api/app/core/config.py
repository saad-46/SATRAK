"""Application configuration.

Settings are loaded from environment variables (prefixed ``SATRAK_API_``) and an
optional ``.env`` file, validated by Pydantic at startup so the process fails fast
with a clear error instead of a runtime ``KeyError`` deep into a request.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment. Drives logging format, docs exposure, etc."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    """Validated application settings.

    Only non-secret, environment-shaped values live here. Secrets arrive via the
    same env vars but are injected from a secrets manager in deployed environments
    (never committed). See ``.env.example``.
    """

    model_config = SettingsConfigDict(
        env_prefix="SATRAK_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---------------------------------------------------------
    app_name: str = "SATRAK API"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    version: str = "0.1.0"

    # --- HTTP / API ----------------------------------------------------------
    api_v1_prefix: str = "/api/v1"
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Datastores ----------------------------------------------------------
    # Optional so the app can boot for liveness checks without a database
    # present (readiness checks surface the real connectivity state instead).
    database_url: PostgresDsn | None = None
    database_pool_size: int = 5
    database_max_overflow: int = 10
    redis_url: RedisDsn | None = None

    # --- Logging -------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # --- Feature flags -------------------------------------------------------
    # Simple env-driven flags for now; a per-jurisdiction provider
    # (app.shared.services.configuration) supersedes this at runtime later.
    feature_flags: dict[str, bool] = Field(default_factory=dict)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        """Allow a comma-separated string in addition to a JSON list."""
        if isinstance(value, str) and not value.startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def docs_enabled(self) -> bool:
        """Interactive docs are exposed everywhere except production."""
        return self.environment is not Environment.PRODUCTION

    def feature_enabled(self, flag: str) -> bool:
        """Return whether a named feature flag is enabled (default False)."""
        return self.feature_flags.get(flag, False)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (single source of truth per process)."""
    return Settings()
