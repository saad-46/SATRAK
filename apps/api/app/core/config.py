"""Application configuration.

Settings are loaded from environment variables (prefixed ``SATRAK_API_``) and an
optional ``.env`` file, validated by Pydantic at startup so the process fails fast
with a clear error instead of a runtime ``KeyError`` deep into a request.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment. Drives logging format, docs exposure, etc."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


# Asymmetric JWS algorithms only. HS* (shared-secret) and ``none`` are never accepted,
# which also closes the classic "HS256 signed with the public key" confusion attack.
ASYMMETRIC_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
)


def _split_csv(value: object) -> object:
    """Allow a comma-separated string in addition to a JSON list."""
    if isinstance(value, str) and not value.startswith("["):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _require_https_url(value: str, *, field: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{field} must be an https URL without embedded credentials")
    if parsed.fragment:
        raise ValueError(f"{field} must not contain a fragment")
    return value


class AuthSettings(BaseSettings):
    """OIDC access-token validation settings (ADR-0013).

    Nothing here has a built-in identity provider: the issuer, audience(s) and (optionally)
    the JWKS location come from the deployment. With ``enabled`` (the default) the process
    refuses to start unless an issuer and at least one audience are configured.
    """

    model_config = SettingsConfigDict(
        env_prefix="SATRAK_API_AUTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Explicit opt-out for local development/tests only (rejected in staging/production).
    enabled: bool = True
    issuer: str | None = None
    audiences: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Optional; otherwise discovered from ``{issuer}/.well-known/openid-configuration``.
    jwks_url: str | None = None
    allowed_algorithms: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["RS256"])
    clock_skew_seconds: int = Field(default=30, ge=0, le=120)
    jwks_cache_ttl_seconds: int = Field(default=300, ge=1)
    # Longest a cached key set may keep validating when the IdP cannot be reached.
    jwks_max_stale_seconds: int = Field(default=3600, ge=0)
    # Floor between network refreshes, so unknown-``kid`` floods cannot cause refresh storms.
    jwks_min_refresh_interval_seconds: int = Field(default=30, ge=1)
    jwks_fetch_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    max_token_bytes: int = Field(default=8192, ge=256, le=65536)

    @field_validator("audiences", "allowed_algorithms", mode="before")
    @classmethod
    def _csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("issuer", "jwks_url")
    @classmethod
    def _https_only(cls, value: str | None, info: object) -> str | None:
        if value is None or value == "":
            return None
        return _require_https_url(value, field=getattr(info, "field_name", "url"))

    @field_validator("allowed_algorithms")
    @classmethod
    def _asymmetric_only(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("allowed_algorithms must not be empty")
        bad = sorted(set(value) - ASYMMETRIC_ALGORITHMS)
        if bad:
            raise ValueError(f"unsupported or insecure algorithms: {', '.join(bad)}")
        return value

    @model_validator(mode="after")
    def _required_when_enabled(self) -> AuthSettings:
        if self.enabled and (not self.issuer or not self.audiences):
            raise ValueError(
                "authentication is enabled but SATRAK_API_AUTH_ISSUER and "
                "SATRAK_API_AUTH_AUDIENCES are not both configured"
            )
        return self


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
    # Binding to all interfaces is required for the containerized deployment to be
    # reachable; network exposure is controlled at the ingress/gateway layer, not
    # by the bind address (Zero Trust — TDD §11). Overridable via SATRAK_API_HOST.
    host: str = "0.0.0.0"  # nosec B104
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Datastores ----------------------------------------------------------
    # Optional so the app can boot for liveness checks without a database
    # present (readiness checks surface the real connectivity state instead).
    database_url: PostgresDsn | None = None
    database_pool_size: int = 5
    database_max_overflow: int = 10
    redis_url: RedisDsn | None = None

    # --- Authentication ------------------------------------------------------
    auth: AuthSettings = Field(default_factory=AuthSettings)

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

    @model_validator(mode="after")
    def _auth_cannot_be_disabled_outside_dev(self) -> Settings:
        if not self.auth.enabled and self.environment in (
            Environment.STAGING,
            Environment.PRODUCTION,
        ):
            raise ValueError("authentication cannot be disabled in staging or production")
        return self

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


class DatabaseUrlSettings(BaseSettings):
    """Just the database URL, for tooling (Alembic) that must not need auth configuration."""

    model_config = SettingsConfigDict(
        env_prefix="SATRAK_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: PostgresDsn | None = None


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (single source of truth per process)."""
    return Settings()
