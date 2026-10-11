"""Job progress/status tracking (Epic 3 Story 16).

``JobTracker`` is the reporting port — the persistent (Redis/DB-backed) tracker is a
future adapter behind the same Protocol; ``InMemoryJobTracker`` is the working in-process
implementation used by tests, local dev, and the inline executor.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from app.contexts.earth_observation.application.jobs.records import (
    JobRecord,
    JobStatus,
    _check_progress,
)
from app.shared.domain.clock import utcnow
from app.shared.domain.errors import BusinessRuleViolation
from app.shared.domain.identifiers import EntityId


class UnknownJobError(BusinessRuleViolation):
    code = "unknown_job"


@runtime_checkable
class JobTracker(Protocol):
    """Records job lifecycle transitions and answers status queries."""

    async def start(
        self,
        *,
        job_id: EntityId,
        task_name: str,
        payload: Mapping[str, str],
        attempt: int,
        max_attempts: int,
    ) -> JobRecord: ...

    async def report_progress(self, job_id: EntityId, *, progress: float) -> None: ...

    async def succeed(self, job_id: EntityId) -> JobRecord: ...

    async def fail(self, job_id: EntityId, *, error: str, will_retry: bool) -> JobRecord: ...

    async def get(self, job_id: EntityId) -> JobRecord | None: ...

    async def list_jobs(self) -> Sequence[JobRecord]: ...


class InMemoryJobTracker:
    """Dict-backed tracker; one record per job id, updated across retries."""

    def __init__(self) -> None:
        self._jobs: dict[EntityId, JobRecord] = {}

    async def start(
        self,
        *,
        job_id: EntityId,
        task_name: str,
        payload: Mapping[str, str],
        attempt: int,
        max_attempts: int,
    ) -> JobRecord:
        existing = self._jobs.get(job_id)
        if existing is not None:
            existing.status = JobStatus.RUNNING
            existing.attempt = attempt
            existing.progress = 0.0
            existing.error = None
            existing.updated_at = utcnow()
            return existing
        record = JobRecord(
            job_id=job_id,
            task_name=task_name,
            payload=dict(payload),
            attempt=attempt,
            max_attempts=max_attempts,
        )
        self._jobs[job_id] = record
        return record

    def _require(self, job_id: EntityId) -> JobRecord:
        record = self._jobs.get(job_id)
        if record is None:
            raise UnknownJobError(f"no job tracked under {job_id}")
        return record

    async def report_progress(self, job_id: EntityId, *, progress: float) -> None:
        _check_progress(progress)
        record = self._require(job_id)
        record.progress = progress
        record.updated_at = utcnow()

    async def succeed(self, job_id: EntityId) -> JobRecord:
        record = self._require(job_id)
        record.status = JobStatus.SUCCEEDED
        record.progress = 1.0
        record.error = None
        record.updated_at = utcnow()
        return record

    async def fail(self, job_id: EntityId, *, error: str, will_retry: bool) -> JobRecord:
        record = self._require(job_id)
        record.status = JobStatus.RETRYING if will_retry else JobStatus.FAILED
        record.error = error
        record.updated_at = utcnow()
        return record

    async def get(self, job_id: EntityId) -> JobRecord | None:
        return self._jobs.get(job_id)

    async def list_jobs(self) -> Sequence[JobRecord]:
        return list(self._jobs.values())
