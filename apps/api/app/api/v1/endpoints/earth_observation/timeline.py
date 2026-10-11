"""Area timeline browsing + property-timeline integration hook (Epic 3 Story 19).

A bounding-box timeline over available imagery. This is the seam the property context
calls with a parcel's bounding box to build a property timeline — without EO importing the
property context (collaboration by geometry + ids, not direct references).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.ratelimit import limit_user
from app.api.v1.endpoints.earth_observation.deps import (
    EoDep,
    SceneReadAccess,
    default_window,
    parse_bbox,
)
from app.api.v1.endpoints.earth_observation.schemas import (
    BoundingBoxSchema,
    SceneSummary,
    TimelineResponse,
)

router = APIRouter(tags=["earth-observation: timeline"])


@router.get(
    "",
    response_model=TimelineResponse,
    summary="Browse imagery timeline for an area",
    dependencies=[Depends(limit_user("eo_search_user"))],
)
async def area_timeline(
    eo: EoDep,
    access: SceneReadAccess,
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat (WGS84)"),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> TimelineResponse:
    area = parse_bbox(bbox)
    scenes = await eo.timeline.timeline(
        area=area,
        window=default_window(from_, to),
        limit=limit,
        scope=access.scope,
    )
    return TimelineResponse(
        area=BoundingBoxSchema.from_domain(area),
        count=len(scenes),
        scenes=[SceneSummary.from_domain(scene) for scene in scenes],
    )
