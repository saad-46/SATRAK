"""Pagination, sorting, and filtering primitives (domain-level).

These are transport-agnostic: the API layer exposes pydantic/query-param wrappers
that translate into these, and repositories translate these into SQL. Centralizing
them means every list endpoint in every future module paginates, sorts, and
filters identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.shared.domain.errors import ValueValidationError

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class FilterOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    IN = "in"
    LIKE = "like"
    CONTAINS = "contains"


@dataclass(frozen=True)
class Sort:
    field: str
    direction: SortDirection = SortDirection.ASC


@dataclass(frozen=True)
class Filter:
    field: str
    operator: FilterOperator
    value: object


@dataclass(frozen=True)
class PageRequest:
    """A request for one page of results, with optional sort/filter/search."""

    page: int = 1
    size: int = DEFAULT_PAGE_SIZE
    sorts: tuple[Sort, ...] = ()
    filters: tuple[Filter, ...] = ()
    search: str | None = None

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueValidationError("page must be >= 1", field="page")
        if not 1 <= self.size <= MAX_PAGE_SIZE:
            raise ValueValidationError(f"size must be between 1 and {MAX_PAGE_SIZE}", field="size")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size


@dataclass(frozen=True)
class Page[T]:
    """A page of results plus the metadata clients need to paginate."""

    items: tuple[T, ...]
    total: int
    page: int
    size: int
    _extra: dict[str, object] = field(default_factory=dict, repr=False)

    @property
    def total_pages(self) -> int:
        if self.size == 0:
            return 0
        return (self.total + self.size - 1) // self.size

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @classmethod
    def create(cls, items: list[T], total: int, request: PageRequest) -> Page[T]:
        return cls(items=tuple(items), total=total, page=request.page, size=request.size)
