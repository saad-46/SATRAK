"""Domain building blocks: Entity, AggregateRoot, ValueObject, events, errors."""

from app.shared.domain.entity import AggregateRoot, Entity, StatefulEntity
from app.shared.domain.enums import EntityStatus
from app.shared.domain.errors import (
    BusinessRuleViolation,
    DomainError,
    InvariantViolation,
    ValueValidationError,
)
from app.shared.domain.events import DomainEvent
from app.shared.domain.identifiers import EntityId, new_id
from app.shared.domain.value_object import ValueObject

__all__ = [
    "AggregateRoot",
    "BusinessRuleViolation",
    "DomainError",
    "DomainEvent",
    "Entity",
    "EntityId",
    "EntityStatus",
    "InvariantViolation",
    "StatefulEntity",
    "ValueObject",
    "ValueValidationError",
    "new_id",
]
