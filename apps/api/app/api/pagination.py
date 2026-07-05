"""Pagination / sorting / filtering query-parameter dependencies.

Endpoints declare ``params: PageParamsDep`` to get validated pagination from the
query string, translated into a transport-agnostic
:class:`~app.shared.pagination.PageRequest` the service/repository layers consume.
Centralizing this makes every list endpoint paginate and sort identically.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query

from app.shared.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PageRequest,
    Sort,
    SortDirection,
)


def _parse_sort(sort: str | None) -> tuple[Sort, ...]:
    """Parse ``?sort=name,-created_at`` into Sort tuples (``-`` prefix = desc)."""
    if not sort:
        return ()
    parsed: list[Sort] = []
    for raw in sort.split(","):
        field = raw.strip()
        if not field:
            continue
        if field.startswith("-"):
            parsed.append(Sort(field=field[1:], direction=SortDirection.DESC))
        else:
            parsed.append(Sort(field=field.lstrip("+"), direction=SortDirection.ASC))
    return tuple(parsed)


class PageParams:
    """Validated pagination inputs bound from query parameters."""

    def __init__(
        self,
        page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
        size: Annotated[
            int, Query(ge=1, le=MAX_PAGE_SIZE, description="Items per page")
        ] = DEFAULT_PAGE_SIZE,
        sort: Annotated[
            str | None, Query(description="Comma-separated fields; prefix '-' for desc")
        ] = None,
        search: Annotated[str | None, Query(description="Free-text search")] = None,
    ) -> None:
        self.page = page
        self.size = size
        self.sort = sort
        self.search = search

    def to_page_request(self) -> PageRequest:
        return PageRequest(
            page=self.page,
            size=self.size,
            sorts=_parse_sort(self.sort),
            search=self.search,
        )


PageParamsDep = Annotated[PageParams, Depends(PageParams)]
