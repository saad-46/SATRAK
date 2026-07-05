"""System endpoints: runtime info and operational metrics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.core.metrics import metrics

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


@router.get("/metrics", summary="Operational metrics snapshot")
async def metrics_snapshot() -> dict[str, Any]:
    return metrics.snapshot()
