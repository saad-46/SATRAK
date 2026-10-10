"""AOI search, details, and history (Epic 3 Story 19).

AOI listing is low-cardinality (wards/cities), so the in-memory adapter lists then
paginates; a future SQL adapter pushes paging down. An AOI's history is the timeline of
available scenes over its footprint.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.pagination import PageParamsDep
from app.api.schemas import PageResponse
from app.api.v1.endpoints.earth_observation.deps import EoDep, default_window
from app.api.v1.endpoints.earth_observation.schemas import (
    AoiDetail,
    AoiSummary,
    BoundingBoxSchema,
    SceneSummary,
    TimelineResponse,
)
from app.core.exceptions import NotFoundError
from app.shared.pagination import Page

router = APIRouter(tags=["earth-observation: aoi"])

_LIST_CAP = 10_000


@router.get("", response_model=PageResponse[AoiSummary], summary="Search AOIs")
async def list_aois(
    eo: EoDep,
    params: PageParamsDep,
    active_only: bool = Query(True, description="Only ACTIVE AOIs"),
) -> PageResponse[AoiSummary]:
    if active_only:
        items = list(await eo.aois.list_active(limit=_LIST_CAP, offset=0))
    else:
        items = list(await eo.aois.list(limit=_LIST_CAP, offset=0))
    request = params.to_page_request()
    window = items[request.offset : request.offset + request.limit]
    page = Page.create([AoiSummary.from_domain(aoi) for aoi in window], len(items), request)
    return PageResponse.from_page(page)


@router.get("/{aoi_id}", response_model=AoiDetail, summary="AOI details")
async def get_aoi(aoi_id: UUID, eo: EoDep) -> AoiDetail:
    aoi = await eo.aois.get(aoi_id)
    if aoi is None:
        raise NotFoundError(f"AOI {aoi_id} not found")
    return AoiDetail.from_domain(aoi)


@router.get("/{aoi_id}/timeline", response_model=TimelineResponse, summary="AOI imagery history")
async def get_aoi_timeline(
    aoi_id: UUID,
    eo: EoDep,
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> TimelineResponse:
    aoi = await eo.aois.get(aoi_id)
    if aoi is None:
        raise NotFoundError(f"AOI {aoi_id} not found")
    scenes = await eo.timeline.timeline(
        area=aoi.bounding_box, window=default_window(from_, to), limit=limit
    )
    return TimelineResponse(
        area=BoundingBoxSchema.from_domain(aoi.bounding_box),
        count=len(scenes),
        scenes=[SceneSummary.from_domain(scene) for scene in scenes],
    )
