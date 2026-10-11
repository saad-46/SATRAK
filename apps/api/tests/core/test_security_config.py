"""Startup configuration: staging/production cannot inherit development security settings."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.core.auth.verifier import InvalidTokenError, TokenVerifier
from app.core.config import AuthSettings, Environment, RateLimitSettings, Settings
from tests.auth_support import TestIdp, auth_settings

DEPLOYED = (Environment.STAGING, Environment.PRODUCTION)


def _deployed(environment: Environment, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": environment,
        "network_topology": "behind_proxy",
        "auth": auth_settings(),
        "rate_limit": RateLimitSettings(
            enabled=True, trusted_proxy_hops=1, trusted_proxy_cidrs=["10.0.0.0/8"]
        ),
        "redis_url": "redis://r:6379/0",
        "database_url": "postgresql+asyncpg://u:p@db:5432/satrak",
    }
    base.update(overrides)
    return Settings(**base)


def test_an_unset_environment_is_treated_as_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SATRAK_API_ENVIRONMENT", raising=False)
    assert Settings.model_fields["environment"].default is Environment.PRODUCTION
    # With nothing else configured, the production rules apply and startup is refused.
    with pytest.raises(ValidationError):
        Settings(auth=auth_settings(), _env_file=None)


@pytest.mark.parametrize("environment", DEPLOYED)
def test_a_complete_deployed_configuration_is_accepted(environment: Environment) -> None:
    assert _deployed(environment).environment is environment


@pytest.mark.parametrize("environment", DEPLOYED)
@pytest.mark.parametrize(
    "override",
    [
        {"auth": AuthSettings(enabled=False)},
        {"auth": auth_settings(require_session_identifier=False)},
        {"rate_limit": RateLimitSettings(enabled=False)},
        {"redis_url": None},
        {"database_url": None},
        {"database_role_check": "warn"},
        {"debug": True},
        {"cors_origins": ["*"]},
        {"rate_limit": RateLimitSettings(enabled=True, trusted_proxy_hops=1)},
    ],
    ids=[
        "auth-disabled",
        "session-identifier-optional",
        "rate-limit-disabled",
        "no-redis",
        "no-database",
        "role-check-warn",
        "debug",
        "wildcard-cors",
        "proxy-hops-without-cidrs",
    ],
)
def test_unsafe_or_missing_values_stop_startup(
    environment: Environment, override: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        _deployed(environment, **override)


def test_authentication_needs_an_explicit_issuer_and_audience() -> None:
    with pytest.raises(ValidationError):
        AuthSettings(enabled=True)
    with pytest.raises(ValidationError):
        AuthSettings(enabled=True, issuer="http://insecure.example.invalid", audiences=["a"])


# --- Tokens: mandatory identifiers and bounded lifetime ---------------------------------------


def _verifier(idp: TestIdp, **overrides: Any) -> TokenVerifier:
    from app.core.auth.jwks import JwksKeyProvider

    settings = auth_settings(**overrides)
    return TokenVerifier(settings, JwksKeyProvider(settings, idp.client()))


async def _reason(verifier: TokenVerifier, token: str) -> str:
    with pytest.raises(InvalidTokenError) as exc:
        await verifier.verify(token)
    return exc.value.reason


async def test_a_token_with_neither_sid_nor_jti_is_refused_by_default(idp: TestIdp) -> None:
    token = idp.token(remove=("jti",))
    assert await _reason(_verifier(idp), token) == "missing_session_id"


async def test_either_sid_or_jti_satisfies_the_requirement(idp: TestIdp) -> None:
    verifier = _verifier(idp)
    assert (await verifier.verify(idp.token(claims={"sid": "s-1"}, remove=("jti",)))).session_id
    assert (await verifier.verify(idp.token())).token_id


async def test_the_requirement_can_be_relaxed_only_explicitly(idp: TestIdp) -> None:
    relaxed = _verifier(idp, require_session_identifier=False)
    principal = await relaxed.verify(idp.token(remove=("jti",)))
    assert principal.session_key is None  # such a token can only be revoked per user


async def test_overlong_token_lifetimes_are_refused(idp: TestIdp) -> None:
    import time

    now = int(time.time())
    long_lived = idp.token(claims={"iat": now, "exp": now + 3600})
    assert await _reason(_verifier(idp), long_lived) == "lifetime_too_long"
    await _verifier(idp, max_token_lifetime_seconds=3600).verify(long_lived)  # explicit opt-in


# --- Metric cardinality ----------------------------------------------------------------------
def _counters(name: str) -> list[dict[str, Any]]:
    from app.core.metrics import metrics

    counters = cast("list[dict[str, Any]]", metrics.snapshot()["counters"])
    return [c for c in counters if c["name"] == name]


def test_metric_label_sets_are_capped() -> None:
    from app.core.metrics import MAX_SERIES_PER_METRIC, MetricsRegistry

    registry = MetricsRegistry()
    for index in range(MAX_SERIES_PER_METRIC + 50):
        registry.increment("probe_total", value_label=str(index))
    counters = cast("list[dict[str, Any]]", registry.snapshot()["counters"])
    series = [c for c in counters if c["name"] == "probe_total"]
    assert len(series) == MAX_SERIES_PER_METRIC + 1  # the cap plus one shared overflow bucket
    overflow = [c for c in series if c["labels"] == {"overflow": "true"}]
    assert overflow and overflow[0]["value"] == 50


async def test_unknown_http_methods_share_one_metric_label(idp: TestIdp) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app
    from tests.auth_support import make_settings

    app = create_app(make_settings(), auth=idp.runtime(make_settings().auth))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for method in ("FOO", "BAR", "BAZ"):
            await client.request(method, "/api/v1/health/live")
    methods = {c["labels"].get("method") for c in _counters("http_requests_total")}
    assert methods <= {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "OTHER"}
    assert "OTHER" in methods


def test_general_ip_ceiling_defaults_to_120_per_minute_and_stricter_limits_remain() -> None:
    from app.core.config import DEFAULT_RATE_POLICIES

    ceiling = DEFAULT_RATE_POLICIES["api_ip"]
    assert [(r.limit, r.window_seconds) for r in ceiling] == [(120, 60)]
    assert DEFAULT_RATE_POLICIES["auth_entry_ip"][0].limit < ceiling[0].limit
    assert DEFAULT_RATE_POLICIES["expensive_user"][0].limit < ceiling[0].limit
    assert DEFAULT_RATE_POLICIES["eo_search_user"][0].limit < ceiling[0].limit
    override = RateLimitSettings(overrides={"api_ip": [{"limit": 300, "window_seconds": 60}]})
    assert override.policy("api_ip")[0].limit == 300  # still configurable
