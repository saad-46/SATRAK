"""Service metadata endpoints (version + non-secret runtime info)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.schemas.base import VersionInfo

router = APIRouter(tags=["meta"])


@router.get("/version", response_model=VersionInfo, summary="Service version")
async def version(settings: SettingsDep) -> VersionInfo:
    return VersionInfo(
        name=settings.app_name,
        version=settings.version,
        environment=str(settings.environment),
    )
