"""Health probes.

- ``/health/live``  — liveness: the process is up. No external dependencies, so
  this stays green even without a database, which is what orchestrators want for
  restart decisions.
- ``/health/ready`` — readiness: checks datastore connectivity and returns 503 if
  a required dependency is down, so a not-yet-ready replica is kept out of the
  load balancer rotation.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.api.deps import SettingsDep
from app.db.session import get_engine
from app.schemas.base import DependencyStatus, HealthStatus, ReadinessStatus

router = APIRouter(tags=["health"])


@router.get("/live", response_model=HealthStatus, summary="Liveness probe")
async def liveness() -> HealthStatus:
    return HealthStatus(status="ok")


async def _check_database() -> DependencyStatus:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return DependencyStatus(name="database", healthy=True)
    except Exception as exc:
        return DependencyStatus(name="database", healthy=False, detail=str(exc))


async def _check_redis(settings: SettingsDep) -> DependencyStatus:
    if settings.redis_url is None:
        return DependencyStatus(name="redis", healthy=False, detail="not configured")
    try:
        # Lazy import so the app boots even if redis isn't installed locally.
        from redis.asyncio import Redis

        client = Redis.from_url(str(settings.redis_url))
        try:
            await client.ping()
        finally:
            await client.aclose()
        return DependencyStatus(name="redis", healthy=True)
    except Exception as exc:
        return DependencyStatus(name="redis", healthy=False, detail=str(exc))


@router.get("/ready", response_model=ReadinessStatus, summary="Readiness probe")
async def readiness(settings: SettingsDep, response: Response) -> ReadinessStatus:
    dependencies = [await _check_database(), await _check_redis(settings)]
    all_healthy = all(dep.healthy for dep in dependencies)
    response.status_code = 200 if all_healthy else 503
    return ReadinessStatus(
        status="ready" if all_healthy else "degraded",
        dependencies=dependencies,
    )
