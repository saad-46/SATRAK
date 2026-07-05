"""Tests for the reusable API foundation: system endpoints, pagination, responses."""

from __future__ import annotations

from httpx import AsyncClient

from app.api.pagination import PageParams
from app.api.schemas import PageResponse
from app.shared.pagination import Page, PageRequest, SortDirection


class TestSystemEndpoints:
    async def test_info(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/system/info")
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "SATRAK API"
        assert "feature_flags" in body

    async def test_metrics_counts_requests(self, client: AsyncClient) -> None:
        await client.get("/api/v1/health/live")
        response = await client.get("/api/v1/system/metrics")
        assert response.status_code == 200
        body = response.json()
        assert body["uptime_seconds"] >= 0
        assert any(c["name"] == "http_requests_total" for c in body["counters"])


class TestPageParams:
    def test_defaults(self) -> None:
        req = PageParams().to_page_request()
        assert req.page == 1
        assert req.sorts == ()

    def test_sort_parsing(self) -> None:
        req = PageParams(sort="name,-created_at").to_page_request()
        assert len(req.sorts) == 2
        assert req.sorts[0].field == "name"
        assert req.sorts[0].direction == SortDirection.ASC
        assert req.sorts[1].field == "created_at"
        assert req.sorts[1].direction == SortDirection.DESC


class TestPageResponse:
    def test_from_page(self) -> None:
        page = Page.create(items=[1, 2, 3], total=23, request=PageRequest(page=2, size=10))
        response = PageResponse[int].from_page(page)
        assert response.items == [1, 2, 3]
        assert response.meta.total == 23
        assert response.meta.total_pages == 3
        assert response.meta.has_next is True
        assert response.meta.has_previous is True
