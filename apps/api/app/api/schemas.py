"""Reusable API response schemas.

Standard, generic envelopes every list/detail endpoint reuses so responses are
shaped consistently platform-wide. These pydantic models live in the API layer
(the boundary); they bridge to the transport-agnostic
:class:`app.shared.pagination.Page` produced by application services.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.shared.pagination import Page


class PageMeta(BaseModel):
    page: int
    size: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool


class PageResponse[T](BaseModel):
    """A generic paginated response envelope."""

    items: list[T]
    meta: PageMeta

    @classmethod
    def from_page(cls, page: Page[T]) -> PageResponse[T]:
        return cls(
            items=list(page.items),
            meta=PageMeta(
                page=page.page,
                size=page.size,
                total=page.total,
                total_pages=page.total_pages,
                has_next=page.has_next,
                has_previous=page.has_previous,
            ),
        )
