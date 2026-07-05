"""Domain-layer base abstractions.

These are pure Python (no SQLAlchemy, no FastAPI) so the domain remains testable
and independent of infrastructure — the inner ring of the clean-architecture
dependency rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(kw_only=True)
class Entity:
    """Base domain entity identified by a stable identity, not its attributes."""

    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Entity) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)
