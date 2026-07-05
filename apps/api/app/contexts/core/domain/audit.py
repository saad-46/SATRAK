"""Audit and activity log entities (append-only records)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.shared.domain.entity import Entity
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.identifiers import EntityId


@dataclass(kw_only=True, eq=False)
class AuditLog(Entity):
    """An immutable audit record for legally-defensible traceability (TDD §11).

    Persisted append-only; entities of this type are never updated or deleted.
    """

    actor_id: EntityId | None
    action: str
    subject_type: str
    subject_id: EntityId
    metadata: dict[str, Any] = field(default_factory=dict)

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.action.strip():
            raise InvariantViolation("audit action is required")


@dataclass(kw_only=True, eq=False)
class ActivityLog(Entity):
    """A user-facing activity-feed record (who did what to which subject)."""

    actor_id: EntityId | None
    verb: str
    subject_type: str
    subject_id: EntityId
    summary: str | None = None

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.verb.strip():
            raise InvariantViolation("activity verb is required")
