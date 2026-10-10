"""Story 1 — authentication settings fail fast and cannot be weakened (ADR-0013 B, A11)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import AuthSettings, Environment, Settings
from tests.auth_support import TEST_AUDIENCE, TEST_ISSUER


def test_enabled_without_issuer_or_audience_refuses_to_start() -> None:
    with pytest.raises(ValidationError, match="not both configured"):
        AuthSettings()
    with pytest.raises(ValidationError):
        AuthSettings(issuer=TEST_ISSUER)
    with pytest.raises(ValidationError):
        AuthSettings(audiences=[TEST_AUDIENCE])


def test_default_settings_without_env_do_not_start(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ISSUER", "AUDIENCES", "ENABLED"):
        monkeypatch.delenv(f"SATRAK_API_AUTH_{name}", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("env", [Environment.STAGING, Environment.PRODUCTION])
def test_authentication_cannot_be_disabled_in_staging_or_production(env: Environment) -> None:
    with pytest.raises(ValidationError, match="cannot be disabled"):
        Settings(environment=env, auth=AuthSettings(enabled=False))


def test_authentication_may_be_disabled_explicitly_in_development() -> None:
    settings = Settings(environment=Environment.DEVELOPMENT, auth=AuthSettings(enabled=False))
    assert settings.auth.enabled is False


@pytest.mark.parametrize("alg", ["HS256", "HS512", "none", "NONE", "rs256"])
def test_only_asymmetric_algorithms_are_accepted(alg: str) -> None:
    with pytest.raises(ValidationError, match="unsupported or insecure"):
        AuthSettings(issuer=TEST_ISSUER, audiences=[TEST_AUDIENCE], allowed_algorithms=[alg])


@pytest.mark.parametrize(
    "url",
    [
        "http://issuer.example.invalid",
        "https://user:pass@issuer.example.invalid",
        "https://issuer.example.invalid/#frag",
        "issuer.example.invalid",
    ],
)
def test_issuer_and_jwks_urls_must_be_plain_https(url: str) -> None:
    with pytest.raises(ValidationError):
        AuthSettings(issuer=url, audiences=[TEST_AUDIENCE])
    with pytest.raises(ValidationError):
        AuthSettings(issuer=TEST_ISSUER, audiences=[TEST_AUDIENCE], jwks_url=url)


def test_csv_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SATRAK_API_AUTH_ISSUER", TEST_ISSUER)
    monkeypatch.setenv("SATRAK_API_AUTH_AUDIENCES", "a, b")
    monkeypatch.setenv("SATRAK_API_AUTH_ALLOWED_ALGORITHMS", "RS256,ES256")
    settings = AuthSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.audiences == ["a", "b"]
    assert settings.allowed_algorithms == ["RS256", "ES256"]
