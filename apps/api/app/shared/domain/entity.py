"""Entity and aggregate base classes.

An :class:`Entity` has a stable identity and a lifecycle; two entities are equal
iff they share the same type and id, regardless of attribute values. Every entity
carries the full audit envelope the platform mandates: id, created/updated
timestamps and actors, an optimistic-concurrency ``version``, and soft-delete
flags.

An :class:`AggregateRoot` is the consistency boundary and the only kind of entity
that records :class:`~app.shared.domain.events.DomainEvent`\\s. Application
services pull those events after a successful commit and hand them to the event
bus.

Business *workflows* are intentionally NOT implemented here (per Epic 2 scope) —
only the reusable lifecycle mechanics that every future aggregate builds on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.shared.domain.clock import utcnow
from app.shared.domain.enums import EntityStatus
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.events import DomainEvent
from app.shared.domain.identifiers import EntityId, new_id


@dataclass(kw_only=True, eq=False)
class Entity:
    """Base class for all domain entities."""

    id: EntityId = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    created_by: EntityId | None = None
    updated_by: EntityId | None = None
    version: int = 1
    is_deleted: bool = False
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        self._check_invariants()

    # --- Invariants ----------------------------------------------------------
    def _check_invariants(self) -> None:
        """Validate the entity is in a consistent state.

        Subclasses override and call ``super()._check_invariants()``. Raising
        :class:`InvariantViolation` here is the single chokepoint that keeps an
        aggregate from ever being observed in an invalid state.
        """
        if self.version < 1:
            raise InvariantViolation("version must be >= 1")

    # --- Lifecycle -----------------------------------------------------------
    def touch(self, *, actor: EntityId | None = None) -> None:
        """Record a mutation: bump version, stamp updated_at/updated_by."""
        self.updated_at = utcnow()
        self.updated_by = actor
        self.version += 1
        self._check_invariants()

    def soft_delete(self, *, actor: EntityId | None = None) -> None:
        if self.is_deleted:
            raise InvariantViolation("entity is already deleted")
        self.is_deleted = True
        self.deleted_at = utcnow()
        self.touch(actor=actor)

    def restore(self, *, actor: EntityId | None = None) -> None:
        if not self.is_deleted:
            raise InvariantViolation("entity is not deleted")
        self.is_deleted = False
        self.deleted_at = None
        self.touch(actor=actor)

    # --- Identity semantics --------------------------------------------------
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Entity) and type(self) is type(other) and self.id == other.id

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.id))


@dataclass(kw_only=True, eq=False)
class StatefulEntity(Entity):
    """An entity that also carries a generic lifecycle status."""

    status: EntityStatus = EntityStatus.ACTIVE

    def activate(self, *, actor: EntityId | None = None) -> None:
        self.status = EntityStatus.ACTIVE
        self.touch(actor=actor)

    def deactivate(self, *, actor: EntityId | None = None) -> None:
        self.status = EntityStatus.INACTIVE
        self.touch(actor=actor)

    def archive(self, *, actor: EntityId | None = None) -> None:
        self.status = EntityStatus.ARCHIVED
        self.touch(actor=actor)


@dataclass(kw_only=True, eq=False)
class AggregateRoot(Entity):
    """Consistency boundary; the only entity kind that records domain events."""

    _events: list[DomainEvent] = field(default_factory=list, repr=False, compare=False)

    def record_event(self, event: DomainEvent) -> None:
        """Append an event to be dispatched after a successful commit."""
        self._events.append(event)

    def pull_events(self) -> list[DomainEvent]:
        """Return and clear pending events (called by the unit of work)."""
        events = list(self._events)
        self._events.clear()
        return events

    @property
    def has_pending_events(self) -> bool:
        return bool(self._events)
