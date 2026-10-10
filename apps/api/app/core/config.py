"""Application configuration.

Settings are loaded from environment variables (prefixed ``SATRAK_API_``) and an
optional ``.env`` file, validated by Pydantic at startup so the process fails fast
with a clear error instead of a runtime ``KeyError`` deep into a request.
"""

from __future__ import annotations

import ipaddress
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, PostgresDsn, RedisDsn, field_validator, model_validator
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
    # Revocation needs a per-session handle: ``sid`` (preferred) or ``jti``. Tokens carrying
    # neither can only be revoked per user, so they are refused unless this is switched off
    # (dev/test only; rejected in staging/production).
    require_session_identifier: bool = True
    # Longest accepted ``exp - iat`` (PRD: 15-minute access tokens). Bounds how long a token
    # stays usable if the IdP disables a user without telling SATRAK, and bounds session-registry
    # growth. Raise it only after revisiting the one-minute revocation requirement (NFR-18.2).
    max_token_lifetime_seconds: int = Field(default=900, ge=60, le=86400)
    # How long after a session's token expired its registry row is kept before pruning. The row
    # is needed only until the token expires (a revoked token must stay refused); the value is an
    # engineering placeholder, NOT a legal retention period: confirm against the records policy.
    session_retention_days: int = Field(default=30, ge=1, le=3650)

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


class RatePolicySpec(BaseModel):
    """``limit`` requests per ``window_seconds`` (one rule of a named policy)."""

    limit: int = Field(gt=0)
    window_seconds: int = Field(gt=0)


# Starting values approved by the owner (2026-10-10) except where marked PROPOSED, which the
# owner has not yet seen; tune all of them from measured traffic. Each named policy is a list
# of rules that must all pass. Scope (per user / per IP) is fixed by the code that applies it.
DEFAULT_RATE_POLICIES: dict[str, list[RatePolicySpec]] = {
    "auth_entry_ip": [RatePolicySpec(limit=10, window_seconds=60)],
    "auth_failure_ip": [RatePolicySpec(limit=10, window_seconds=60)],
    "api_user": [RatePolicySpec(limit=120, window_seconds=60)],
    "eo_search_user": [RatePolicySpec(limit=30, window_seconds=60)],
    "expensive_user": [
        RatePolicySpec(limit=5, window_seconds=60),
        RatePolicySpec(limit=30, window_seconds=3600),
    ],
    "admin_user": [RatePolicySpec(limit=10, window_seconds=60)],
    # Owner decision 2026-10-10: tiles start at 120/min/user, configurable separately. The IP
    # abuse ceiling is separately configurable; its value is an engineering placeholder to be
    # validated by load and abuse testing, not an owner-approved figure.
    "api_ip": [RatePolicySpec(limit=600, window_seconds=60)],
    "tiles_user": [RatePolicySpec(limit=120, window_seconds=60)],
}


class RateLimitSettings(BaseSettings):
    """Distributed rate limiting (Redis). Policy values are overridable per environment."""

    model_config = SettingsConfigDict(
        env_prefix="SATRAK_API_RATE_LIMIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    enabled: bool = True
    # Replace individual named policies (JSON), e.g. {"eo_search_user": [{"limit": 60, ...}]}.
    overrides: dict[str, list[RatePolicySpec]] = Field(default_factory=dict)
    # Number of trusted reverse proxies in front of the API. 0 = use the TCP peer address and
    # ignore X-Forwarded-For entirely (a client-supplied header must never pick its own IP).
    trusted_proxy_hops: int = Field(default=0, ge=0, le=10)
    # Networks the reverse proxies connect from. When set, X-Forwarded-For is believed only if the
    # TCP peer is inside one of them, so connecting to the API directly cannot spoof an address.
    # Required (non-empty) whenever trusted_proxy_hops > 0 in staging and production.
    trusted_proxy_cidrs: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Progressive throttling after repeated authentication failures from one IP.
    penalty_base_seconds: int = Field(default=60, gt=0)
    penalty_max_seconds: int = Field(default=3600, gt=0)
    # Process-local budget (requests per minute per key) used for *ordinary* requests while
    # Redis is unavailable. Auth and expensive operations fail closed instead (503).
    fallback_per_minute: int = Field(default=60, gt=0)
    # Connections the limiter may open per process; callers queue (up to 1 s) beyond this.
    redis_max_connections: int = Field(default=100, ge=1, le=10000)

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def _cidr_csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def _valid_cidrs(cls, value: list[str]) -> list[str]:
        for entry in value:
            network = ipaddress.ip_network(entry, strict=False)  # raises ValueError on garbage
            if network.prefixlen == 0:  # 0.0.0.0/0 or ::/0 would trust every peer
                raise ValueError("trusted_proxy_cidrs must not trust every address")
        return value

    @property
    def trusted_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for entry in self.trusted_proxy_cidrs:
            network = ipaddress.ip_network(entry, strict=False)
            if (
                isinstance(network, ipaddress.IPv6Network)
                and network.prefixlen >= 96
                and network.network_address.ipv4_mapped is not None
            ):
                # ``::ffff:10.0.0.0/104`` means 10.0.0.0/8: peers are compared as IPv4.
                network = ipaddress.ip_network(
                    (network.network_address.ipv4_mapped, network.prefixlen - 96), strict=False
                )
            networks.append(network)
        return networks

    @model_validator(mode="after")
    def _known_policies_only(self) -> RateLimitSettings:
        unknown = set(self.overrides) - set(DEFAULT_RATE_POLICIES)
        if unknown:
            raise ValueError(f"unknown rate limit policies: {sorted(unknown)}")
        return self

    def policy(self, name: str) -> list[RatePolicySpec]:
        return self.overrides.get(name, DEFAULT_RATE_POLICIES[name])


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
    # Fail-secure default: an unset value is treated as production, so a deployment that forgets
    # SATRAK_API_ENVIRONMENT gets the strictest validation instead of silently inheriting
    # development behaviour. Local development sets it to ``development`` in ``.env``.
    environment: Environment = Environment.PRODUCTION
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
    # ``enforce`` refuses to start when the application's database role could bypass row-level
    # security (superuser, BYPASSRLS, table owner, ...). ``warn`` only logs and is rejected in
    # staging and production.
    database_role_check: Literal["enforce", "warn"] = "enforce"
    database_pool_size: int = 5
    database_max_overflow: int = 10
    redis_url: RedisDsn | None = None

    # --- Authentication ------------------------------------------------------
    auth: AuthSettings = Field(default_factory=AuthSettings)

    # --- Rate limiting and request hardening ---------------------------------
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    max_request_body_bytes: int = Field(default=1_048_576, gt=0)  # 1 MiB; uploads use storage

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

    @model_validator(mode="after")
    def _hardening_cannot_be_disabled_outside_dev(self) -> Settings:
        if not self.rate_limit.enabled and self.environment in (
            Environment.STAGING,
            Environment.PRODUCTION,
        ):
            raise ValueError("rate limiting cannot be disabled in staging or production")
        if self.database_role_check != "enforce" and self.environment in (
            Environment.STAGING,
            Environment.PRODUCTION,
        ):
            raise ValueError("database_role_check must be 'enforce' in staging or production")
        if (
            self.rate_limit.trusted_proxy_hops > 0
            and not self.rate_limit.trusted_proxy_cidrs
            and self.environment in (Environment.STAGING, Environment.PRODUCTION)
        ):
            raise ValueError(
                "rate_limit.trusted_proxy_cidrs is required when trusted_proxy_hops > 0 "
                "in staging or production"
            )
        if not self.auth.require_session_identifier and self.environment in (
            Environment.STAGING,
            Environment.PRODUCTION,
        ):
            raise ValueError("auth.require_session_identifier cannot be disabled in staging/prod")
        if self.debug and self.environment in (Environment.STAGING, Environment.PRODUCTION):
            raise ValueError("debug cannot be enabled in staging or production")
        if self.database_url is None and self.environment in (
            Environment.STAGING,
            Environment.PRODUCTION,
        ):
            raise ValueError("database_url is required in staging or production")
        if "*" in self.cors_origins:
            raise ValueError("cors_origins must list explicit origins (credentials are allowed)")
        if (
            self.rate_limit.enabled
            and self.redis_url is None
            and self.environment
            in (
                Environment.STAGING,
                Environment.PRODUCTION,
            )
        ):
            raise ValueError("rate limiting requires redis_url in staging or production")
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
    # Migrations run as the schema owner (satrak_migrator), never as the application role.
    migration_database_url: PostgresDsn | None = None


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (single source of truth per process)."""
    return Settings()
