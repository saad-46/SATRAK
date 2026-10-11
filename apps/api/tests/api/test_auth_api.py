"""Story 1 — HTTP authentication behaviour and the route inventory (A1, A8, A11)."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import AuthSettings, Environment, Settings
from app.core.security_audit import InMemorySecurityAuditLog
from app.main import create_app
from tests.auth_support import TestIdp, auth_settings, make_settings
from tests.authz_support import InMemoryAccessStore

# The complete public allow-list. Anything else must require authentication.
PUBLIC_PATHS = frozenset(
    {
        "/",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/meta/version",
    }
)
DOC_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def _operations(app: FastAPI) -> list[tuple[str, str]]:
    """Every (method, path) the application serves, from its published OpenAPI schema."""
    schema = app.openapi()
    return [
        (method.upper(), path)
        for path, item in schema["paths"].items()
        for method in item
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    ]


@pytest.fixture
def app(settings: Settings, idp: TestIdp) -> FastAPI:
    # An empty in-memory access store: authentication succeeds, authorization (default deny)
    # then yields 403 on permissioned routes — never 401, and never 503 from a missing database.
    return create_app(
        settings,
        auth=idp.runtime(settings.auth),
        access=InMemoryAccessStore(),
        audit=InMemorySecurityAuditLog(),
    )


def _protected(app: FastAPI) -> list[tuple[str, str]]:
    return [(m, _concrete(p)) for m, p in _operations(app) if p not in PUBLIC_PATHS]


def test_public_allow_list_has_no_stale_entries(app: FastAPI) -> None:
    served = {path for _, path in _operations(app)}
    assert PUBLIC_PATHS - {"/"} <= served


def test_route_inventory_is_not_empty_and_includes_eo_and_system(app: FastAPI) -> None:
    paths = {path for _, path in _operations(app)}
    assert any(p.startswith("/api/v1/eo/") for p in paths)
    assert any(p.startswith("/api/v1/system/") for p in paths)


async def test_every_protected_route_rejects_missing_and_bad_tokens(
    app: FastAPI, idp: TestIdp
) -> None:
    bad_headers = [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer not.a.jwt"},
        {"Authorization": "bearer"},
        idp.bearer(claims={"aud": "other"}),
        idp.bearer(claims={"iss": "https://evil.example.invalid"}),
        idp.bearer(claims={"exp": 1, "iat": 0}),
        idp.bearer(headers={"kid": "nope"}),
        {"Authorization": f"Token {idp.token()}"},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for method, path in _protected(app):
            for headers in bad_headers:
                response = await client.request(method, path, headers=headers)
                assert response.status_code == 401, (method, path, headers)
                assert response.headers["content-type"].startswith("application/problem+json")
                assert response.headers["www-authenticate"].startswith("Bearer")


async def test_every_protected_route_accepts_a_valid_token(app: FastAPI, idp: TestIdp) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for method, path in _protected(app):
            response = await client.request(method, path, headers=idp.bearer())
            assert response.status_code not in (401, 503), (method, path)


async def test_missing_credentials_vs_invalid_token_challenge(app: FastAPI, idp: TestIdp) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/api/v1/system/info")
        invalid = await client.get("/api/v1/system/info", headers={"Authorization": "Bearer x.y.z"})
    assert missing.status_code == invalid.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert 'error="invalid_token"' in invalid.headers["www-authenticate"]
    assert missing.json()["code"] == "authentication_required"
    assert invalid.json()["code"] == "invalid_token"


async def test_failure_body_does_not_leak_the_reason(app: FastAPI, idp: TestIdp) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/system/info", headers=idp.bearer(claims={"aud": "x"}))
    body = response.text.lower()
    assert "audience" not in body and "bad_audience" not in body


async def test_duplicate_authorization_headers_are_rejected(app: FastAPI, idp: TestIdp) -> None:
    transport = ASGITransport(app=app)
    token = idp.token()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/system/info",
            headers=[("Authorization", f"Bearer {token}"), ("Authorization", f"Bearer {token}")],
        )
    assert response.status_code == 401


async def test_tenant_and_identity_headers_are_ignored_for_authentication(
    app: FastAPI, idp: TestIdp
) -> None:
    transport = ASGITransport(app=app)
    spoofed = {
        "X-Forwarded-User": "admin",
        "X-User-Id": "admin",
        "X-Jurisdiction-Id": "everything",
        "X-Forwarded-For": "127.0.0.1",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/system/info", headers=spoofed)
    assert response.status_code == 401


async def test_method_variants_and_trailing_slash_do_not_bypass(app: FastAPI, idp: TestIdp) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            r = await client.request(method, "/api/v1/eo/scenes")
            assert r.status_code in (401, 405)
        slash = await client.get("/api/v1/eo/scenes/", follow_redirects=True)
        assert slash.status_code in (401, 404)
        override = await client.get(
            "/api/v1/eo/scenes", headers={"X-HTTP-Method-Override": "OPTIONS"}
        )
        assert override.status_code == 401


async def test_public_routes_stay_public(app: FastAPI) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in PUBLIC_PATHS:
            assert (await client.get(path)).status_code != 401, path


async def test_signing_keys_unavailable_fails_closed_with_503(settings: Settings) -> None:
    idp = TestIdp()
    idp.online = False
    app = create_app(settings, auth=idp.runtime(settings.auth))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/system/info", headers=idp.bearer())
    assert response.status_code == 503
    assert response.json()["code"] == "auth_unavailable"


async def test_disabled_authentication_is_only_possible_by_explicit_dev_setting() -> None:
    dev = Settings(
        environment=Environment.DEVELOPMENT, log_format="console", auth=AuthSettings(enabled=False)
    )
    app = create_app(dev)
    assert app.state.auth is None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/system/info")).status_code == 200


async def test_docs_are_not_exposed_in_production() -> None:
    prod = Settings(
        environment=Environment.PRODUCTION,
        log_format="console",
        auth=auth_settings(),
        redis_url="redis://localhost:6379/0",  # required in production (rate limiting)
        database_url="postgresql+asyncpg://u:p@localhost:5432/satrak",
    )
    app = create_app(prod, auth=TestIdp().runtime(prod.auth))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in DOC_PATHS - {"/docs/oauth2-redirect"}:
            assert (await client.get(path)).status_code == 404, path


def test_helper_settings_default_to_enabled_authentication() -> None:
    assert make_settings().auth.enabled is True
