"""Organization aggregate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.shared.domain.entity import AggregateRoot
from app.shared.domain.enums import EntityStatus
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.events import EntityCreated, EntityUpdated
from app.shared.domain.identifiers import EntityId
from app.shared.value_objects.address import Address
from app.shared.value_objects.contact_information import ContactInformation


class OrganizationType(StrEnum):
    STATE = "state"
    DEPARTMENT = "department"
    MUNICIPAL_CORPORATION = "municipal_corporation"
    ZONE = "zone"
    WARD = "ward"
    OTHER = "other"


@dataclass(kw_only=True, eq=False)
class Organization(AggregateRoot):
    """A government organization node in the jurisdiction hierarchy."""

    name: str
    code: str
    type: OrganizationType = OrganizationType.OTHER
    status: EntityStatus = EntityStatus.ACTIVE
    parent_id: EntityId | None = None
    description: str | None = None
    contact: ContactInformation | None = None
    address: Address | None = None

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.name.strip():
            raise InvariantViolation("organization name is required")
        if not self.code.strip():
            raise InvariantViolation("organization code is required")

    @classmethod
    def create(
        cls,
        *,
        name: str,
        code: str,
        type: OrganizationType = OrganizationType.OTHER,
        parent_id: EntityId | None = None,
        actor: EntityId | None = None,
    ) -> Organization:
        org = cls(
            name=name,
            code=code,
            type=type,
            parent_id=parent_id,
            created_by=actor,
            updated_by=actor,
        )
        org.record_event(EntityCreated(aggregate_id=org.id, aggregate_type=cls.__name__))
        return org

    def rename(self, new_name: str, *, actor: EntityId | None = None) -> None:
        self.name = new_name
        self._check_invariants()
        self.touch(actor=actor)
        self.record_event(
            EntityUpdated(
                aggregate_id=self.id, aggregate_type=type(self).__name__, changed_fields=("name",)
            )
        )
