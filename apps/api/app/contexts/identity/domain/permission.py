"""Permission entity — an atomic (resource, action) grant."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain.entity import Entity
from app.shared.domain.errors import InvariantViolation


@dataclass(kw_only=True, eq=False)
class Permission(Entity):
    """A single permission, e.g. resource=``case`` action=``dispatch_drone``.

    ``code`` is the canonical ``<resource>:<action>`` string used in policy checks.
    """

    resource: str
    action: str
    description: str | None = None

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.resource.strip():
            raise InvariantViolation("permission resource is required")
        if not self.action.strip():
            raise InvariantViolation("permission action is required")

    @property
    def code(self) -> str:
        return f"{self.resource}:{self.action}"
