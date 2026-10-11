"""Job status records (Epic 3 Story 16)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.shared.domain.clock import utcnow
from app.shared.domain.errors import ValueValidationError
from app.shared.domain.identifiers import EntityId


class JobStatus(StrEnum):
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class JobRecord:
    """Point-in-time state of one background job execution (across retries)."""

    job_id: EntityId
    task_name: str
    payload: dict[str, str]
    status: JobStatus = JobStatus.RUNNING
    attempt: int = 1
    max_attempts: int = 3
    progress: float = 0.0
    error: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.attempt < 1 or self.max_attempts < 1:
            raise ValueValidationError("attempt counters must be >= 1", field="attempt")
        _check_progress(self.progress)

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.SUCCEEDED, JobStatus.FAILED)


def _check_progress(value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueValidationError("progress must be in [0, 1]", field="progress")
