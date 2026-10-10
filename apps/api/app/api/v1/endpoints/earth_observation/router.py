"""Aggregate Earth Observation router (mounted at /api/v1/eo)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints.earth_observation import aoi, scenes, tiles, timeline

eo_router = APIRouter(prefix="/eo")
eo_router.include_router(scenes.router, prefix="/scenes")
eo_router.include_router(tiles.router, prefix="/scenes/{scene_id}/tiles")
eo_router.include_router(aoi.router, prefix="/aoi")
eo_router.include_router(timeline.router, prefix="/timeline")
