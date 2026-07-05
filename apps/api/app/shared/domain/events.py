"""Domain events.

A domain event is an immutable record that something meaningful happened in the
domain. Aggregates raise events (see :class:`AggregateRoot`); the event bus
(:mod:`app.shared.events.bus`) dispatches them to handlers. Events are pure
data — no behavior, no infrastructure — so they can be logged, persisted to an
audit trail, or published to an external broker later without change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from app.shared.domain.clock import utcnow


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base class for all domain events."""

    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=utcnow)

    @property
    def name(self) -> str:
        """Stable event name (the class name) used for routing/logging."""
        return type(self).__name__


@dataclass(frozen=True, kw_only=True)
class EntityEvent(DomainEvent):
    """Base for events that concern a specific entity/aggregate instance."""

    aggregate_id: UUID
    aggregate_type: str


@dataclass(frozen=True, kw_only=True)
class EntityCreated(EntityEvent):
    """A new entity was created."""


@dataclass(frozen=True, kw_only=True)
class EntityUpdated(EntityEvent):
    """An entity's state changed. ``changed_fields`` lists mutated attributes."""

    changed_fields: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class EntityDeleted(EntityEvent):
    """An entity was (soft) deleted."""

    soft: bool = True


@dataclass(frozen=True, kw_only=True)
class FileUploaded(DomainEvent):
    """A file/document was uploaded to storage."""

    file_id: UUID
    storage_key: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True, kw_only=True)
class TaskAssigned(DomainEvent):
    """A task was assigned to an actor."""

    task_id: UUID
    assignee_id: UUID
    assigned_by: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class NotificationCreated(DomainEvent):
    """A notification was created for a recipient."""

    notification_id: UUID
    recipient_id: UUID
    channel: str


@dataclass(frozen=True, kw_only=True)
class CommentAdded(DomainEvent):
    """A comment was added to a subject entity."""

    comment_id: UUID
    subject_type: str
    subject_id: UUID
    author_id: UUID


@dataclass(frozen=True, kw_only=True)
class AuditRecorded(DomainEvent):
    """An auditable action was recorded."""

    actor_id: UUID | None
    action: str
    subject_type: str
    subject_id: UUID
    metadata: dict[str, Any] = field(default_factory=dict)
