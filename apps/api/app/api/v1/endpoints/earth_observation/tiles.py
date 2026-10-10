"""XYZ tile serving with version-aware, cache-validated responses (Epic 3 Story 18).

Tiles are read from object storage by their deterministic, pipeline-version-scoped key
(Story 9). The response carries a strong ``ETag`` (the tile's content hash) so clients and
CDNs can revalidate cheaply — an ``If-None-Match`` hit returns ``304 Not Modified``. The
served pipeline version defaults to the scene's current one and can be pinned via
``?version=`` for reproducible/historical tiles. No UI.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.api.v1.endpoints.earth_observation.deps import EoDep
from app.api.v1.endpoints.earth_observation.schemas import TileMetadataResponse
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.value_objects.tile import (
    TileCoord,
    TileMatrixSetRef,
)
from app.core.exceptions import NotFoundError
from app.shared.services.storage import StoredObject

router = APIRouter(tags=["earth-observation: tiles"])

_TMS = TileMatrixSetRef.web_mercator_quad()
_TILE_EXTENSION = "bin"
_CACHE_CONTROL = "public, max-age=3600"


async def _resolve_version(scene_id: UUID, eo: EoDep, version: str | None) -> tuple[Scene, str]:
    scene = await eo.scenes.get(scene_id)
    if scene is None:
        raise NotFoundError(f"scene {scene_id} not found")
    resolved = version if version is not None else scene.pipeline_version
    if resolved is None:
        raise NotFoundError(f"scene {scene_id} has no processed tiles yet")
    return scene, resolved


def _tile_key(eo: EoDep, scene_id: UUID, version: str, z: int, x: int, y: int) -> str:
    # TileCoord validates z/x/y (out-of-range -> 422 via the domain error handler).
    return eo.keys.tile_key(
        tile_matrix_set=_TMS,
        scene_id=scene_id,
        pipeline_version=version,
        tile=TileCoord(z=z, x=x, y=y),
        extension=_TILE_EXTENSION,
    )


async def _open_tile(eo: EoDep, key: str, z: int, x: int, y: int, scene_id: UUID) -> StoredObject:
    try:
        return await eo.storage.open(key)
    except KeyError as exc:
        raise NotFoundError(f"tile {z}/{x}/{y} not found for scene {scene_id}") from exc


def _etag(data: bytes) -> str:
    return f'"{hashlib.sha256(data).hexdigest()}"'


@router.get("/{z}/{x}/{y}", summary="Serve an XYZ tile", response_class=Response)
async def get_tile(
    scene_id: UUID,
    z: int,
    x: int,
    y: int,
    eo: EoDep,
    version: str | None = Query(None, description="Pin a pipeline version"),
    if_none_match: str | None = Header(None),
) -> Response:
    _, resolved = await _resolve_version(scene_id, eo, version)
    key = _tile_key(eo, scene_id, resolved, z, x, y)
    obj = await _open_tile(eo, key, z, x, y, scene_id)
    etag = _etag(obj.data)
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": _CACHE_CONTROL})
    return Response(
        content=obj.data,
        media_type=obj.content_type,
        headers={"ETag": etag, "Cache-Control": _CACHE_CONTROL},
    )


@router.get(
    "/{z}/{x}/{y}/metadata",
    response_model=TileMetadataResponse,
    summary="Tile metadata",
)
async def get_tile_metadata(
    scene_id: UUID,
    z: int,
    x: int,
    y: int,
    eo: EoDep,
    version: str | None = Query(None, description="Pin a pipeline version"),
) -> TileMetadataResponse:
    _, resolved = await _resolve_version(scene_id, eo, version)
    key = _tile_key(eo, scene_id, resolved, z, x, y)
    obj = await _open_tile(eo, key, z, x, y, scene_id)
    return TileMetadataResponse(
        scene_id=scene_id,
        z=z,
        x=x,
        y=y,
        tile_matrix_set=_TMS.identifier,
        pipeline_version=resolved,
        storage_key=key,
        etag=_etag(obj.data),
        size_bytes=len(obj.data),
        content_type=obj.content_type,
    )
