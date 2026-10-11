"""Story 6 — baseline HTTP controls: CORS, security headers, body limits, log hygiene (A12)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Environment, RateLimitSettings, Settings
from app.main import create_app
from tests.auth_support import TestIdp, auth_settings
from tests.authz_support import MemoryWorld

ORIGIN = "http://localhost:3000"


def _settings(**kw: object) -> Settings:
    return Settings(
        environment=Environment.TEST,
        log_format="console",
        auth=auth_settings(),
        rate_limit=RateLimitSettings(enabled=False),
        **kw,  # type: ignore[arg-type]
    )


async def _client(idp: TestIdp, settings: Settings) -> AsyncClient:
    world = MemoryWorld()
    uid = await world.user("user-123")
    world.store.users[uid] = ("https://issuer.example.invalid", "user-123", "active")
    app = create_app(
        settings, auth=idp.runtime(settings.auth), access=world.store, audit=world.audit
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --- CORS ------------------------------
def test_wildcard_cors_origins_are_rejected_because_credentials_are_allowed() -> None:
    with pytest.raises(ValueError, match="explicit origins"):
        _settings(cors_origins=["*"])


async def test_cors_allows_only_configured_origins_and_never_echoes_a_wildcard(
    idp: TestIdp,
) -> None:
    async with await _client(idp, _settings()) as client:
        ok = await client.options(
            "/api/v1/system/info",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert ok.headers["access-control-allow-origin"] == ORIGIN
        assert ok.headers["access-control-allow-credentials"] == "true"
        evil = await client.options(
            "/api/v1/system/info",
            headers={
                "Origin": "https://evil.example.invalid",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in evil.headers
        odd_header = await client.options(
            "/api/v1/system/info",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Jurisdiction-Id",
            },
        )
        assert odd_header.status_code == 400  # identity-like headers are not CORS-allowed


# --- Security headers ------------------------------
async def test_security_headers_on_api_and_error_responses(idp: TestIdp) -> None:
    async with await _client(idp, _settings()) as client:
        for response in (
            await client.get("/api/v1/health/live"),
            await client.get("/api/v1/system/info"),  # 401
            await client.get("/api/v1/system/info", headers=idp.bearer()),  # 200
            await client.get("/nope"),  # 404
        ):
            h = response.headers
            assert h["x-content-type-options"] == "nosniff"
            assert h["x-frame-options"] == "DENY"
            assert h["referrer-policy"] == "no-referrer"
            assert "frame-ancestors 'none'" in h["content-security-policy"]
            assert h["cache-control"] == "no-store"
            assert "strict-transport-security" not in h  # only behind TLS in production
        docs = await client.get("/docs")
        assert "content-security-policy" not in docs.headers


async def test_hsts_is_sent_in_production(idp: TestIdp) -> None:
    prod = Settings(
        environment=Environment.PRODUCTION,
        network_topology="direct",
        direct_exposure_acknowledgement="TEST-APPROVAL-1",
        log_format="console",
        auth=auth_settings(),
        redis_url="redis://localhost:6379/0",
        database_url="postgresql+asyncpg://u:p@localhost:5432/satrak",
    )
    app = create_app(prod, auth=idp.runtime(prod.auth))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/v1/health/live")
    assert "max-age=31536000" in r.headers["strict-transport-security"]


# --- Body size ------------------------------
async def test_oversized_bodies_are_rejected_before_the_handler_runs(idp: TestIdp) -> None:
    async with await _client(idp, _settings(max_request_body_bytes=1000)) as client:
        headers = idp.bearer(claims={"sub": "user-123"})
        declared = await client.post("/api/v1/auth/logout", content=b"x" * 5000, headers=headers)
        assert declared.status_code == 413
        assert declared.json()["code"] == "payload_too_large"

        small = await client.post("/api/v1/auth/logout", content=b"x" * 100, headers=headers)
        assert small.status_code == 204


async def test_streamed_bodies_without_content_length_are_counted_as_they_arrive() -> None:
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from app.core.security_middleware import BodySizeLimitMiddleware

    async def consume(request: Request) -> PlainTextResponse:
        return PlainTextResponse(str(len(await request.body())))

    app = Starlette(
        routes=[Route("/", consume, methods=["POST"])],
        middleware=[Middleware(BodySizeLimitMiddleware, max_bytes=1000)],
    )

    async def chunks():  # no Content-Length header: sizes are only known as chunks arrive
        for _ in range(10):
            yield b"y" * 500

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/", content=chunks())).status_code == 413
        assert (await client.post("/", content=b"z" * 900)).text == "900"


# --- Log hygiene ------------------------------
async def test_tokens_and_credentials_never_reach_the_logs(
    idp: TestIdp, capsys: pytest.CaptureFixture[str]
) -> None:
    token = idp.token(claims={"sub": "user-123", "sid": "log-test"})
    wrong_aud = idp.token(claims={"aud": "elsewhere"})
    async with await _client(idp, _settings()) as client:
        await client.get("/api/v1/system/info", headers={"Authorization": f"Bearer {token}"})
        await client.get("/api/v1/eo/aoi", headers={"Authorization": f"Bearer {token}"})  # 403
        await client.get("/api/v1/system/info", headers={"Authorization": f"Bearer {wrong_aud}"})
        await client.get("/api/v1/system/info", headers={"Authorization": "Bearer junk.junk.junk"})
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "request_completed" in output  # the logs were actually captured
    for secret in (token, wrong_aud, "junk.junk.junk", token.split(".")[1], token.split(".")[2]):
        assert secret not in output
    assert "Bearer" not in output
