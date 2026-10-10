"""Health probes.

- ``/health/live``  — liveness: the process is up. No external dependencies, so
  this stays green even without a database, which is what orchestrators want for
  restart decisions.
- ``/health/ready`` — readiness: checks datastore connectivity and returns 503 if
  a required dependency is down, so a not-yet-ready replica is kept out of the
  load balancer rotation.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from app.db.session import get_engine
from app.schemas.base import DependencyStatus, HealthStatus, ReadinessStatus

router = APIRouter(tags=["health"])


@router.get("/live", response_model=HealthStatus, summary="Liveness probe")
async def liveness() -> HealthStatus:
    return HealthStatus(status="ok")


logger = structlog.get_logger("api.health")


_CACHE_SECONDS = 2.0  # bounds database/Redis probing no matter how often this is called
_PROBE_TIMEOUT_SECONDS = 2.0


async def _check_database() -> DependencyStatus:
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        return DependencyStatus(name="database", healthy=True)
    except Exception as exc:
        logger.warning("readiness_check_failed", dependency="database", cause=str(exc))
        return DependencyStatus(name="database", healthy=False, detail="unavailable")


async def _check_redis(request: Request) -> DependencyStatus:
    client = getattr(request.app.state, "redis_client", None)
    if client is None:
        return DependencyStatus(name="redis", healthy=False, detail="unavailable")
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            await client.ping()  # the shared, bounded pool: no new connection per probe
        return DependencyStatus(name="redis", healthy=True)
    except Exception as exc:
        logger.warning("readiness_check_failed", dependency="redis", cause=str(exc))
        return DependencyStatus(name="redis", healthy=False, detail="unavailable")


@router.get(
    "/ready",
    response_model=ReadinessStatus,
    summary="Readiness probe",
)
async def readiness(request: Request, response: Response) -> ReadinessStatus:
    cached = getattr(request.app.state, "readiness_cache", None)
    if cached is None or time.monotonic() - cached[0] > _CACHE_SECONDS:
        lock = getattr(request.app.state, "readiness_lock", None)
        if lock is None:  # one probe at a time: concurrent callers share its result
            lock = request.app.state.readiness_lock = asyncio.Lock()
        async with lock:
            cached = getattr(request.app.state, "readiness_cache", None)  # filled while waiting
            if cached is None or time.monotonic() - cached[0] > _CACHE_SECONDS:
                dependencies = [await _check_database(), await _check_redis(request)]
                healthy = all(dep.healthy for dep in dependencies)
                cached = (
                    time.monotonic(),
                    ReadinessStatus(
                        status="ready" if healthy else "degraded", dependencies=dependencies
                    ),
                )
                request.app.state.readiness_cache = cached
    status = cached[1]
    response.status_code = 200 if status.status == "ready" else 503
    return status
