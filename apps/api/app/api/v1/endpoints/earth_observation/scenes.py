"""Scene search, details, status, history, and metadata (Epic 3 Story 17).

Read endpoints over the scene repository / query service — no business logic is duplicated
here; search and history are the same paginated query ordered newest-acquisition first.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.pagination import PageParamsDep
from app.api.ratelimit import limit_user
from app.api.schemas import PageResponse
from app.api.v1.endpoints.earth_observation.deps import (
    EoDep,
    SceneReadAccess,
    optional_window,
    parse_bbox,
)
from app.api.v1.endpoints.earth_observation.schemas import (
    SceneDetail,
    SceneMetadataResponse,
    SceneStatusResponse,
    SceneSummary,
)
from app.contexts.earth_observation.domain.enums import SceneStatus, SensorType
from app.contexts.earth_observation.domain.ports.repositories import SceneQuery
from app.core.exceptions import NotFoundError
from app.shared.pagination import Page

router = APIRouter(tags=["earth-observation: scenes"])


@router.get(
    "",
    response_model=PageResponse[SceneSummary],
    summary="Search scenes",
    dependencies=[Depends(limit_user("eo_search_user"))],
)
async def search_scenes(
    eo: EoDep,
    access: SceneReadAccess,
    params: PageParamsDep,
    bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat (WGS84)"),
    from_: datetime | None = Query(None, alias="from", description="Acquired at or after"),
    to: datetime | None = Query(None, description="Acquired at or before"),
    status: SceneStatus | None = Query(None, description="Lifecycle status filter"),
    provider: str | None = Query(None, description="Provider key filter"),
    sensor_type: SensorType | None = Query(None, description="Sensor modality filter"),
    max_cloud: float | None = Query(None, ge=0, le=100, description="Max cloud cover %"),
) -> PageResponse[SceneSummary]:
    query = SceneQuery(
        area=parse_bbox(bbox) if bbox else None,
        window=optional_window(from_, to),
        statuses=frozenset({status}) if status is not None else frozenset(),
        provider=provider,
        sensor_type=sensor_type,
        max_cloud_cover_pct=max_cloud,
        jurisdiction_ids=access.jurisdictions,
    )
    request = params.to_page_request()
    page = await eo.scene_query.search(query, request=request)
    mapped = Page.create(
        [SceneSummary.from_domain(scene) for scene in page.items], page.total, request
    )
    return PageResponse.from_page(mapped)


@router.get("/{scene_id}", response_model=SceneDetail, summary="Scene details")
async def get_scene(scene_id: UUID, eo: EoDep, access: SceneReadAccess) -> SceneDetail:
    scene = await eo.scenes.get(scene_id)
    if scene is None:
        raise NotFoundError(f"scene {scene_id} not found")
    access.require(scene.jurisdiction_id)
    return SceneDetail.from_domain(scene)


@router.get("/{scene_id}/status", response_model=SceneStatusResponse, summary="Scene status")
async def get_scene_status(
    scene_id: UUID, eo: EoDep, access: SceneReadAccess
) -> SceneStatusResponse:
    scene = await eo.scenes.get(scene_id)
    if scene is None:
        raise NotFoundError(f"scene {scene_id} not found")
    access.require(scene.jurisdiction_id)
    return SceneStatusResponse.from_domain(scene)


@router.get("/{scene_id}/metadata", response_model=SceneMetadataResponse, summary="Scene metadata")
async def get_scene_metadata(
    scene_id: UUID, eo: EoDep, access: SceneReadAccess
) -> SceneMetadataResponse:
    scene = await eo.scenes.get(scene_id)
    if scene is None:
        raise NotFoundError(f"scene {scene_id} not found")
    access.require(scene.jurisdiction_id)
    return SceneMetadataResponse.from_domain(scene)
