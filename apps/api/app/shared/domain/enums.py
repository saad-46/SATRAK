"""Shared domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class EntityStatus(StrEnum):
    """Generic lifecycle status applicable to most stateful entities.

    Bounded contexts may define their own richer status enums where a workflow
    demands it; this covers the common create/deactivate/archive lifecycle.
    """

    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class Priority(StrEnum):
    """Generic priority scale reused by tasks, notifications, and cases."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
