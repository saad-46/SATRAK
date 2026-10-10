"""Area of Interest aggregate — a monitored geographic footprint.

An AOI is what acquisition is scheduled against (spec §13 ``aoi_definitions``). It owns its
geometry as a WGS84 bounding box, a monitoring priority, and an optional revisit cadence.
Its relationship to imagery is expressed as deterministic bounding-box intersection — no
PostGIS/GIS here (that lands in the GIS context / infrastructure).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain.entity import AggregateRoot
from app.shared.domain.enums import EntityStatus, Priority
from app.shared.domain.errors import InvariantViolation, ValueValidationError
from app.shared.domain.events import EntityCreated, EntityUpdated
from app.shared.domain.identifiers import EntityId
from app.shared.value_objects.geo import BoundingBox, Coordinates


@dataclass(kw_only=True, eq=False)
class AreaOfInterest(AggregateRoot):
    """A named, monitored area that scenes are acquired for."""

    name: str
    bounding_box: BoundingBox
    status: EntityStatus = EntityStatus.ACTIVE
    priority: Priority = Priority.MEDIUM
    jurisdiction_id: EntityId | None = None
    revisit_cadence_days: int | None = None

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.name.strip():
            raise InvariantViolation("AOI name is required")
        if self.revisit_cadence_days is not None and self.revisit_cadence_days <= 0:
            raise InvariantViolation("revisit_cadence_days must be a positive integer")

    @classmethod
    def create(
        cls,
        *,
        name: str,
        bounding_box: BoundingBox,
        priority: Priority = Priority.MEDIUM,
        jurisdiction_id: EntityId | None = None,
        revisit_cadence_days: int | None = None,
        actor: EntityId | None = None,
    ) -> AreaOfInterest:
        aoi = cls(
            name=name,
            bounding_box=bounding_box,
            priority=priority,
            jurisdiction_id=jurisdiction_id,
            revisit_cadence_days=revisit_cadence_days,
            created_by=actor,
            updated_by=actor,
        )
        aoi.record_event(EntityCreated(aggregate_id=aoi.id, aggregate_type=cls.__name__))
        return aoi

    # --- Mutations -----------------------------------------------------------
    def rename(self, new_name: str, *, actor: EntityId | None = None) -> None:
        self.name = new_name
        self._check_invariants()
        self.touch(actor=actor)
        self._record_updated(("name",))

    def update_geometry(self, bounding_box: BoundingBox, *, actor: EntityId | None = None) -> None:
        self.bounding_box = bounding_box
        self.touch(actor=actor)
        self._record_updated(("bounding_box",))

    def set_priority(self, priority: Priority, *, actor: EntityId | None = None) -> None:
        self.priority = priority
        self.touch(actor=actor)
        self._record_updated(("priority",))

    def set_revisit_cadence(self, days: int | None, *, actor: EntityId | None = None) -> None:
        self.revisit_cadence_days = days
        self._check_invariants()
        self.touch(actor=actor)
        self._record_updated(("revisit_cadence_days",))

    def activate(self, *, actor: EntityId | None = None) -> None:
        self.status = EntityStatus.ACTIVE
        self.touch(actor=actor)
        self._record_updated(("status",))

    def deactivate(self, *, actor: EntityId | None = None) -> None:
        self.status = EntityStatus.INACTIVE
        self.touch(actor=actor)
        self._record_updated(("status",))

    def _record_updated(self, changed_fields: tuple[str, ...]) -> None:
        self.record_event(
            EntityUpdated(
                aggregate_id=self.id,
                aggregate_type=type(self).__name__,
                changed_fields=changed_fields,
            )
        )

    # --- Relationships to imagery (deterministic bbox geometry) --------------
    def contains(self, point: Coordinates) -> bool:
        return self.bounding_box.contains(point)

    def intersects(self, other: BoundingBox) -> bool:
        """Whether a scene footprint (as a bbox) overlaps this AOI."""
        box = self.bounding_box
        if other.srid != box.srid:
            raise ValueValidationError(
                f"cannot compare boxes in different CRS ({other.srid} vs {box.srid})",
                field="srid",
            )
        return not (
            other.min_longitude > box.max_longitude
            or other.max_longitude < box.min_longitude
            or other.min_latitude > box.max_latitude
            or other.max_latitude < box.min_latitude
        )

    @property
    def is_active(self) -> bool:
        return self.status is EntityStatus.ACTIVE
