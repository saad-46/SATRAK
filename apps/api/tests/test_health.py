"""Tests for health probes."""

from __future__ import annotations

from httpx import AsyncClient


async def test_liveness_returns_200(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_liveness_sets_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.headers.get("X-Request-ID")


async def test_readiness_reports_degraded_without_datastores(client: AsyncClient) -> None:
    # No database/redis configured in the TEST settings -> readiness is degraded.
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert {dep["name"] for dep in body["dependencies"]} == {"database", "redis"}
