"""UserProfile aggregate — a person's profile within the platform.

Distinct from the authentication principal (a later epic): this is the domain
projection of a user — display info, org/department placement, and assigned roles.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.shared.domain.entity import AggregateRoot
from app.shared.domain.enums import EntityStatus
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.events import EntityCreated
from app.shared.domain.identifiers import EntityId
from app.shared.value_objects.email import Email
from app.shared.value_objects.phone_number import PhoneNumber


@dataclass(kw_only=True, eq=False)
class UserProfile(AggregateRoot):
    display_name: str
    email: Email
    status: EntityStatus = EntityStatus.ACTIVE
    phone: PhoneNumber | None = None
    organization_id: EntityId | None = None
    department_id: EntityId | None = None
    role_ids: set[EntityId] = field(default_factory=set)

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.display_name.strip():
            raise InvariantViolation("display_name is required")

    @classmethod
    def create(
        cls,
        *,
        display_name: str,
        email: Email,
        organization_id: EntityId | None = None,
        actor: EntityId | None = None,
    ) -> UserProfile:
        profile = cls(
            display_name=display_name,
            email=email,
            organization_id=organization_id,
            created_by=actor,
            updated_by=actor,
        )
        profile.record_event(EntityCreated(aggregate_id=profile.id, aggregate_type=cls.__name__))
        return profile

    def assign_role(self, role_id: EntityId, *, actor: EntityId | None = None) -> None:
        if role_id not in self.role_ids:
            self.role_ids.add(role_id)
            self.touch(actor=actor)

    def remove_role(self, role_id: EntityId, *, actor: EntityId | None = None) -> None:
        if role_id in self.role_ids:
            self.role_ids.discard(role_id)
            self.touch(actor=actor)
