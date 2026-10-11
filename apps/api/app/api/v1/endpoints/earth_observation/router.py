"""Aggregate Earth Observation router (mounted at /api/v1/eo)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.ratelimit import limit_user
from app.api.v1.endpoints.earth_observation import aoi, scenes, tiles, timeline

eo_router = APIRouter(prefix="/eo")
# Per-route budgets: ordinary reads share ``api_user``; map tiles have their own larger budget
# (a single map view fetches dozens of tiles); search routes add ``eo_search_user`` below.
_ordinary = [Depends(limit_user("api_user"))]
eo_router.include_router(scenes.router, prefix="/scenes", dependencies=_ordinary)
eo_router.include_router(
    tiles.router,
    prefix="/scenes/{scene_id}/tiles",
    dependencies=[Depends(limit_user("tiles_user"))],
)
eo_router.include_router(aoi.router, prefix="/aoi", dependencies=_ordinary)
eo_router.include_router(timeline.router, prefix="/timeline", dependencies=_ordinary)
