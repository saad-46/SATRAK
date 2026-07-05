"""Base Pydantic schemas and shared response contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    """Base for all API schemas: ORM-friendly, forbids unknown fields on input."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class HealthStatus(BaseSchema):
    """Liveness response."""

    status: str = "ok"


class DependencyStatus(BaseSchema):
    """Health of a single downstream dependency."""

    name: str
    healthy: bool
    detail: str | None = None


class ReadinessStatus(BaseSchema):
    """Readiness response aggregating dependency health."""

    status: str
    dependencies: list[DependencyStatus]


class VersionInfo(BaseSchema):
    """Service version/build metadata."""

    name: str
    version: str
    environment: str


class Page[T](BaseSchema):
    """Generic pagination envelope for future list endpoints."""

    items: list[T]
    total: int
    page: int
    page_size: int
