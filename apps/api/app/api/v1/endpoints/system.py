"""System endpoints: runtime info and operational metrics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import AccessStoreDep, SettingsDep, require_permission
from app.core.authz import AccessContext
from app.core.metrics import metrics

METRICS_PERMISSION = "system:metrics:read"

router = APIRouter(tags=["system"])


@router.get("/info", summary="Runtime info (non-secret)")
async def info(settings: SettingsDep) -> dict[str, Any]:
    return {
        "name": settings.app_name,
        "version": settings.version,
        "environment": str(settings.environment),
        "api_prefix": settings.api_v1_prefix,
        "feature_flags": settings.feature_flags,
    }


@router.get(
    "/metrics", summary="Operational metrics (platform operators only)", response_model=None
)
async def metrics_snapshot(
    store: AccessStoreDep,
    format: str = Query("json", pattern="^(json|prometheus)$"),
    ctx: AccessContext = Depends(require_permission(METRICS_PERMISSION)),
) -> Response | dict[str, Any]:
    """Counters include rate-limiter degraded mode (``rate_limiter_unavailable_total``).

    Process-wide data, so it needs ``system:metrics:read`` held at national scope.
    """
    if not await store.covers_national(within=ctx.jurisdictions):
        raise ctx.denial()
    if format == "prometheus":
        return Response(
            metrics.render_prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    return metrics.snapshot()
