"""Department entity (belongs to an Organization)."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain.entity import StatefulEntity
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.identifiers import EntityId


@dataclass(kw_only=True, eq=False)
class Department(StatefulEntity):
    """A department within an organization, optionally nested."""

    organization_id: EntityId
    name: str
    code: str
    parent_department_id: EntityId | None = None

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.name.strip():
            raise InvariantViolation("department name is required")
        if not self.code.strip():
            raise InvariantViolation("department code is required")
