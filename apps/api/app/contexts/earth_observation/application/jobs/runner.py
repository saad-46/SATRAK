"""Framework-independent job runner (Epic 3 Story 16).

Executes EO background tasks behind the shared ``TaskQueue`` port — never binding to
Celery (ADR-0008: Celery is a later adapter in ``infrastructure/jobs`` that simply calls
``JobRunner.execute``). Responsibilities:

- **Pipeline chaining**: on success, the next stage is enqueued with the merged payload
  (ingest -> validate -> extract-metadata -> preprocess -> tiles), replicating the spec
  §12 task chain without a central orchestrator. A handler can halt the chain (e.g. a
  scene rejected by validation is an outcome, not an error).
- **Retry handling**: a failed attempt below ``max_attempts`` re-enqueues the same task
  with ``attempt + 1`` under the same job id (status RETRYING); backoff *timing* is the
  executor's concern (Celery countdown / beat), keeping this runner deterministic.
- **Failure handling**: exhausted attempts mark the job FAILED with the error preserved.
- **Progress/status**: handlers report progress through the tracker; status is queryable
  per job id.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import structlog

from app.contexts.earth_observation.application.acquisition.discover_scenes import (
    INGEST_SCENE_TASK,
)
from app.contexts.earth_observation.application.jobs.records import JobRecord
from app.contexts.earth_observation.application.jobs.tracker import JobTracker
from app.shared.domain.errors import BusinessRuleViolation
from app.shared.domain.identifiers import EntityId, new_id, parse_id
from app.shared.domain.scope import OutOfScopeError, TenantScope
from app.shared.services.background_task import BackgroundTask, TaskQueue

logger = structlog.get_logger("eo.jobs")

TASK_INGEST_SCENE = INGEST_SCENE_TASK
TASK_VALIDATE_SCENE = "earth_observation.validate_scene"
TASK_EXTRACT_METADATA = "earth_observation.extract_metadata"
TASK_PREPROCESS_SCENE = "earth_observation.preprocess_scene"
TASK_GENERATE_TILES = "earth_observation.generate_tiles"
TASK_GENERATE_THUMBNAIL = "earth_observation.generate_thumbnail"

# The spec §12 ingestion chain; thumbnails run inside preprocessing (Story 13 hook) and
# as a standalone re-generation task outside the chain.
DEFAULT_CHAIN: Mapping[str, str] = {
    TASK_INGEST_SCENE: TASK_VALIDATE_SCENE,
    TASK_VALIDATE_SCENE: TASK_EXTRACT_METADATA,
    TASK_EXTRACT_METADATA: TASK_PREPROCESS_SCENE,
    TASK_PREPROCESS_SCENE: TASK_GENERATE_TILES,
}


class UnknownTaskError(BusinessRuleViolation):
    code = "unknown_task"


class MissingPayloadField(BusinessRuleViolation):
    code = "missing_payload_field"


def scope_from_payload(payload: Mapping[str, str]) -> TenantScope:
    """The tenant a task acts for. A payload can only *narrow* work to one jurisdiction; it can
    never name the all-tenants scope, which only code-defined system jobs may construct."""
    try:
        jurisdiction_id = parse_id(require_field(payload, "jurisdiction_id"))
    except ValueError as exc:
        raise MissingPayloadField("jurisdiction_id is not a valid identifier") from exc
    return TenantScope(frozenset({jurisdiction_id}))


def require_field(payload: Mapping[str, str], name: str) -> str:
    value = payload.get(name)
    if value is None or not value.strip():
        raise MissingPayloadField(f"job payload is missing required field {name!r}")
    return value


@dataclass(frozen=True)
class HandlerResult:
    """What a handler contributes to the pipeline after succeeding."""

    payload_update: Mapping[str, str] = field(default_factory=dict)
    halt_chain: bool = False


class ProgressReporter(Protocol):
    def __call__(self, progress: float) -> Awaitable[None]: ...


@runtime_checkable
class JobHandler(Protocol):
    """One unit of background work; raises to signal a retryable failure."""

    def __call__(
        self, payload: Mapping[str, str], *, progress: ProgressReporter
    ) -> Awaitable[HandlerResult]: ...


class JobRunner:
    """Executes tasks, tracks status, retries failures, and chains pipeline stages."""

    def __init__(
        self,
        *,
        tracker: JobTracker,
        queue: TaskQueue,
        max_attempts: int = 3,
        chain: Mapping[str, str] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise BusinessRuleViolation("max_attempts must be >= 1")
        self._tracker = tracker
        self._queue = queue
        self._max_attempts = max_attempts
        self._chain = dict(chain) if chain is not None else dict(DEFAULT_CHAIN)
        self._handlers: dict[str, JobHandler] = {}

    def register(self, task_name: str, handler: JobHandler) -> None:
        if task_name in self._handlers:
            raise BusinessRuleViolation(f"handler for {task_name!r} already registered")
        self._handlers[task_name] = handler

    @property
    def task_names(self) -> Sequence[str]:
        return tuple(self._handlers)

    async def execute(self, task: BackgroundTask) -> JobRecord:
        handler = self._handlers.get(task.name)
        if handler is None:
            raise UnknownTaskError(f"no handler registered for task {task.name!r}")

        payload = {str(key): str(value) for key, value in task.payload.items()}
        attempt = int(payload.get("attempt", "1"))
        job_id: EntityId = parse_id(payload["job_id"]) if "job_id" in payload else new_id()
        await self._tracker.start(
            job_id=job_id,
            task_name=task.name,
            payload=payload,
            attempt=attempt,
            max_attempts=self._max_attempts,
        )

        async def report(progress: float) -> None:
            await self._tracker.report_progress(job_id, progress=progress)

        try:
            result = await handler(payload, progress=report)
        except OutOfScopeError as exc:
            # A task naming a record outside its own jurisdiction is a violation, not a transient
            # fault: never retried and logged for review (ids only, no tenant data).
            logger.warning(
                "pipeline_scope_violation",
                task=task.name,
                job_id=str(job_id),
                payload_jurisdiction_id=payload.get("jurisdiction_id"),
                record_jurisdiction_id=str(exc.jurisdiction_id),
            )
            return await self._tracker.fail(
                job_id, error="record is outside the task's jurisdiction", will_retry=False
            )
        except Exception as exc:
            will_retry = attempt < self._max_attempts
            record = await self._tracker.fail(job_id, error=str(exc), will_retry=will_retry)
            if will_retry:
                await self._queue.enqueue(
                    BackgroundTask(
                        name=task.name,
                        payload={**payload, "attempt": str(attempt + 1), "job_id": str(job_id)},
                    )
                )
            return record

        record = await self._tracker.succeed(job_id)
        next_task = self._chain.get(task.name)
        if next_task is not None and not result.halt_chain:
            next_payload = {
                "scene_id": require_field(payload, "scene_id"),
                "jurisdiction_id": require_field(payload, "jurisdiction_id"),
                **{str(k): str(v) for k, v in result.payload_update.items()},
            }
            await self._queue.enqueue(BackgroundTask(name=next_task, payload=next_payload))
        return record
