"""Audit service abstraction.

The platform's evidentiary integrity requirement (TDD §11) demands an immutable
record of who did what, when. This defines the audit *port*; a hash-chained /
WORM-backed implementation is added in the security epic. In-memory sink supports
tests and local development.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.shared.domain.clock import utcnow


@dataclass(frozen=True)
class AuditEntry:
    """A single audit record."""

    action: str
    subject_type: str
    subject_id: UUID
    actor_id: UUID | None = None
    at: datetime = field(default_factory=utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AuditSink(Protocol):
    async def record(self, entry: AuditEntry) -> None: ...


class InMemoryAuditSink:
    """Collects audit entries in a list. For tests."""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)
