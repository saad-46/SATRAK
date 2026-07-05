"""Task aggregate — a generic assignable unit of work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.shared.domain.entity import AggregateRoot
from app.shared.domain.enums import Priority
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.events import EntityCreated, TaskAssigned
from app.shared.domain.identifiers import EntityId


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass(kw_only=True, eq=False)
class Task(AggregateRoot):
    title: str
    status: TaskStatus = TaskStatus.OPEN
    priority: Priority = Priority.MEDIUM
    description: str | None = None
    assignee_id: EntityId | None = None
    due_at: datetime | None = None

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.title.strip():
            raise InvariantViolation("task title is required")

    @classmethod
    def create(
        cls,
        *,
        title: str,
        priority: Priority = Priority.MEDIUM,
        actor: EntityId | None = None,
    ) -> Task:
        task = cls(title=title, priority=priority, created_by=actor, updated_by=actor)
        task.record_event(EntityCreated(aggregate_id=task.id, aggregate_type=cls.__name__))
        return task

    def assign(self, assignee_id: EntityId, *, actor: EntityId | None = None) -> None:
        self.assignee_id = assignee_id
        self.touch(actor=actor)
        self.record_event(
            TaskAssigned(task_id=self.id, assignee_id=assignee_id, assigned_by=actor)
        )

    def mark_in_progress(self, *, actor: EntityId | None = None) -> None:
        self.status = TaskStatus.IN_PROGRESS
        self.touch(actor=actor)

    def complete(self, *, actor: EntityId | None = None) -> None:
        if self.status is TaskStatus.CANCELLED:
            raise InvariantViolation("cannot complete a cancelled task")
        self.status = TaskStatus.DONE
        self.touch(actor=actor)
