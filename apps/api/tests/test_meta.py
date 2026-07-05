"""Tests for metadata endpoints and the error envelope."""

from __future__ import annotations

from httpx import AsyncClient


async def test_version_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/meta/version")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "SATRAK API"
    assert body["environment"] == "test"
    assert "version" in body


async def test_root_endpoint(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "SATRAK API"


async def test_unknown_route_returns_problem_details(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert body["code"] == "http_404"
    assert body["instance"] == "/api/v1/does-not-exist"
    assert "request_id" in body
