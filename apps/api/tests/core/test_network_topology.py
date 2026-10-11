"""The declared network topology must agree with proxy trust, and cannot weaken anything else."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Environment, RateLimitSettings, Settings
from tests.auth_support import auth_settings

DEPLOYED = (Environment.STAGING, Environment.PRODUCTION)
ACK = "APPROVAL-0001"
PROXIED = {"trusted_proxy_hops": 1, "trusted_proxy_cidrs": ["10.0.0.0/8"]}


def _settings(
    environment: Environment, rate: dict[str, Any] | None = None, **extra: Any
) -> Settings:
    return Settings(
        environment=environment,
        auth=auth_settings(),
        rate_limit=RateLimitSettings(enabled=True, **(rate or {})),
        redis_url="redis://r:6379/0",
        database_url="postgresql+asyncpg://u:p@db:5432/satrak",
        _env_file=None,  # type: ignore[call-arg]
        **extra,
    )


@pytest.mark.parametrize("environment", DEPLOYED)
def test_deployed_environments_have_no_implicit_topology(environment: Environment) -> None:
    assert Settings.model_fields["network_topology"].default is None
    with pytest.raises(ValidationError, match="network_topology is required"):
        _settings(environment)


@pytest.mark.parametrize("value", ["", "proxy", "BEHIND_PROXY", "none", "auto"])
def test_unknown_topology_values_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError, match="network_topology"):
        _settings(Environment.PRODUCTION, PROXIED, network_topology=value)


def test_an_empty_environment_variable_is_not_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SATRAK_API_NETWORK_TOPOLOGY", "")
    with pytest.raises(ValidationError, match="network_topology"):
        _settings(Environment.DEVELOPMENT)


@pytest.mark.parametrize("environment", DEPLOYED)
def test_behind_proxy_is_accepted_only_with_trusted_proxy_settings(
    environment: Environment,
) -> None:
    ok = _settings(environment, PROXIED, network_topology="behind_proxy")
    assert ok.network_topology == "behind_proxy"
    for rate in ({}, {"trusted_proxy_hops": 1}, {"trusted_proxy_cidrs": ["10.0.0.0/8"]}):
        with pytest.raises(ValidationError, match="behind_proxy needs"):
            _settings(environment, rate, network_topology="behind_proxy")


@pytest.mark.parametrize("environment", DEPLOYED)
def test_behind_proxy_never_takes_an_acknowledgement(environment: Environment) -> None:
    with pytest.raises(ValidationError, match="applies only to direct"):
        _settings(
            environment,
            PROXIED,
            network_topology="behind_proxy",
            direct_exposure_acknowledgement=ACK,
        )


@pytest.mark.parametrize("environment", DEPLOYED)
def test_direct_in_a_deployed_environment_needs_a_recorded_acknowledgement(
    environment: Environment,
) -> None:
    for ack in (None, "", "   ", "short"):
        with pytest.raises(ValidationError, match="direct_exposure_acknowledgement"):
            _settings(environment, network_topology="direct", direct_exposure_acknowledgement=ack)
    ok = _settings(environment, network_topology="direct", direct_exposure_acknowledgement=ACK)
    assert ok.network_topology == "direct"


@pytest.mark.parametrize("environment", DEPLOYED)
def test_the_acknowledgement_cannot_turn_on_header_trust(environment: Environment) -> None:
    for rate in (PROXIED, {"trusted_proxy_hops": 1}, {"trusted_proxy_cidrs": ["10.0.0.0/8"]}):
        with pytest.raises(ValidationError, match="direct cannot trust proxies"):
            _settings(
                environment,
                rate,
                network_topology="direct",
                direct_exposure_acknowledgement=ACK,
            )


@pytest.mark.parametrize("environment", DEPLOYED)
def test_the_acknowledgement_does_not_relax_any_other_deployed_rule(
    environment: Environment,
) -> None:
    ack = {"network_topology": "direct", "direct_exposure_acknowledgement": ACK}
    for override in (
        {"database_url": None},
        {"redis_url": None},
        {"debug": True},
        {"cors_origins": ["*"]},
        {"database_role_check": "warn"},
        {"auth": auth_settings(require_session_identifier=False)},
    ):
        with pytest.raises(ValidationError):
            Settings(
                **{
                    "environment": environment,
                    "auth": auth_settings(),
                    "rate_limit": RateLimitSettings(enabled=True),
                    "redis_url": "redis://r:6379/0",
                    "database_url": "postgresql+asyncpg://u:p@db:5432/satrak",
                    **ack,
                    **override,
                },
                _env_file=None,  # type: ignore[call-arg]
            )


def test_an_acknowledgement_without_a_topology_is_rejected() -> None:
    with pytest.raises(ValidationError, match="needs network_topology=direct"):
        _settings(Environment.DEVELOPMENT, direct_exposure_acknowledgement=ACK)


def test_development_may_declare_direct_without_an_acknowledgement() -> None:
    assert (
        _settings(Environment.DEVELOPMENT, network_topology="direct").network_topology == "direct"
    )
    # ...and may still leave it undeclared; only deployed environments insist.
    assert _settings(Environment.DEVELOPMENT).network_topology is None


def test_a_declaration_alone_does_not_make_a_header_believable() -> None:
    from app.api.ratelimit import client_ip
    from tests.core.test_ratelimit import _request

    behind = _settings(Environment.PRODUCTION, PROXIED, network_topology="behind_proxy")
    # Declared behind a proxy, but the caller connected straight to the API: header ignored.
    assert client_ip(_request(behind, "203.0.113.9", "6.6.6.6")) == "203.0.113.9"
    direct = _settings(
        Environment.PRODUCTION, network_topology="direct", direct_exposure_acknowledgement=ACK
    )
    # Direct: no header is ever believed, whoever the peer is, including a private address.
    for peer in ("203.0.113.9", "10.1.2.3", "127.0.0.1"):
        assert client_ip(_request(direct, peer, "6.6.6.6, 7.7.7.7")) == peer
