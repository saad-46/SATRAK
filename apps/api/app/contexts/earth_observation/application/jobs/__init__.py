"""Background processing for the EO pipeline (Epic 3 Story 16).

Framework-independent job runtime over the shared ``TaskQueue`` port: chaining, retries,
failure handling, progress tracking, and status reporting. Celery never appears here —
the Celery adapter (``infrastructure/jobs``, ADR-0008) simply calls ``JobRunner.execute``.
"""

from __future__ import annotations

from app.contexts.earth_observation.application.jobs.handlers import build_default_handlers
from app.contexts.earth_observation.application.jobs.records import JobRecord, JobStatus
from app.contexts.earth_observation.application.jobs.runner import (
    DEFAULT_CHAIN,
    TASK_EXTRACT_METADATA,
    TASK_GENERATE_THUMBNAIL,
    TASK_GENERATE_TILES,
    TASK_INGEST_SCENE,
    TASK_PREPROCESS_SCENE,
    TASK_VALIDATE_SCENE,
    HandlerResult,
    JobHandler,
    JobRunner,
    MissingPayloadField,
    ProgressReporter,
    UnknownTaskError,
    require_field,
)
from app.contexts.earth_observation.application.jobs.tracker import (
    InMemoryJobTracker,
    JobTracker,
    UnknownJobError,
)

__all__ = [
    "DEFAULT_CHAIN",
    "TASK_EXTRACT_METADATA",
    "TASK_GENERATE_THUMBNAIL",
    "TASK_GENERATE_TILES",
    "TASK_INGEST_SCENE",
    "TASK_PREPROCESS_SCENE",
    "TASK_VALIDATE_SCENE",
    "HandlerResult",
    "InMemoryJobTracker",
    "JobHandler",
    "JobRecord",
    "JobRunner",
    "JobStatus",
    "JobTracker",
    "MissingPayloadField",
    "ProgressReporter",
    "UnknownJobError",
    "UnknownTaskError",
    "build_default_handlers",
    "require_field",
]
