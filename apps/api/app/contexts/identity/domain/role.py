"""Role aggregate — a named bundle of permissions."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.shared.domain.entity import AggregateRoot
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.events import EntityCreated
from app.shared.domain.identifiers import EntityId


@dataclass(kw_only=True, eq=False)
class Role(AggregateRoot):
    """A role grouping permissions, optionally scoped to a jurisdiction."""

    name: str
    code: str
    is_system: bool = False
    jurisdiction_id: EntityId | None = None
    permission_ids: set[EntityId] = field(default_factory=set)

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.name.strip():
            raise InvariantViolation("role name is required")
        if not self.code.strip():
            raise InvariantViolation("role code is required")

    @classmethod
    def create(
        cls, *, name: str, code: str, is_system: bool = False, actor: EntityId | None = None
    ) -> Role:
        role = cls(name=name, code=code, is_system=is_system, created_by=actor, updated_by=actor)
        role.record_event(EntityCreated(aggregate_id=role.id, aggregate_type=cls.__name__))
        return role

    def grant(self, permission_id: EntityId, *, actor: EntityId | None = None) -> None:
        if permission_id not in self.permission_ids:
            self.permission_ids.add(permission_id)
            self.touch(actor=actor)

    def revoke(self, permission_id: EntityId, *, actor: EntityId | None = None) -> None:
        if permission_id in self.permission_ids:
            self.permission_ids.discard(permission_id)
            self.touch(actor=actor)

    def has_permission(self, permission_id: EntityId) -> bool:
        return permission_id in self.permission_ids
