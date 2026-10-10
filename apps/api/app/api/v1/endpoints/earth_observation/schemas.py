"""Response/request schemas for the Earth Observation API (Epic 3 Stories 17-19).

Pydantic models live in the API boundary; each maps *from* a domain object so the domain
never learns about transport. Bounding boxes and metadata are surfaced in WGS84, the
platform interchange CRS.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.shared.value_objects.geo import BoundingBox


class BoundingBoxSchema(BaseModel):
    min_longitude: float
    min_latitude: float
    max_longitude: float
    max_latitude: float
    srid: int

    @classmethod
    def from_domain(cls, box: BoundingBox) -> BoundingBoxSchema:
        return cls(
            min_longitude=box.min_longitude,
            min_latitude=box.min_latitude,
            max_longitude=box.max_longitude,
            max_latitude=box.max_latitude,
            srid=box.srid,
        )


class BandSchema(BaseModel):
    name: str
    index: int
    common_name: str | None
    wavelength_nm: float | None
    gsd_m: float | None


class SceneSummary(BaseModel):
    """Compact scene projection for list/search results."""

    id: UUID
    provider: str
    provider_scene_id: str
    status: str
    sensor_type: str
    acquired_at: datetime
    cloud_cover_pct: float | None
    quality_score: float | None
    bounding_box: BoundingBoxSchema

    @classmethod
    def from_domain(cls, scene: Scene) -> SceneSummary:
        acq = scene.acquisition
        return cls(
            id=scene.id,
            provider=scene.provider_scene_id.provider,
            provider_scene_id=str(scene.provider_scene_id),
            status=scene.status.value,
            sensor_type=acq.sensor_type.value,
            acquired_at=acq.acquired_at,
            cloud_cover_pct=acq.cloud_cover.value if acq.cloud_cover is not None else None,
            quality_score=scene.quality.value if scene.quality is not None else None,
            bounding_box=BoundingBoxSchema.from_domain(scene.bounding_box),
        )


class SceneDetail(SceneSummary):
    """Full scene projection including processing state and lineage."""

    crs_epsg: int | None
    pipeline_version: str | None
    checksum_sha256: str | None
    rejection_reason: str | None
    aoi_ids: list[UUID]
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, scene: Scene) -> SceneDetail:
        summary = SceneSummary.from_domain(scene)
        return cls(
            **summary.model_dump(),
            crs_epsg=scene.crs.epsg if scene.crs is not None else None,
            pipeline_version=scene.pipeline_version,
            checksum_sha256=scene.checksum_sha256,
            rejection_reason=scene.rejection_reason,
            aoi_ids=sorted(scene.aoi_ids, key=str),
            version=scene.version,
            created_at=scene.created_at,
            updated_at=scene.updated_at,
        )


class SceneStatusResponse(BaseModel):
    """Lifecycle status for polling ingestion/processing progress."""

    id: UUID
    status: str
    pipeline_version: str | None
    is_available: bool
    is_terminal: bool
    rejection_reason: str | None
    version: int
    updated_at: datetime

    @classmethod
    def from_domain(cls, scene: Scene) -> SceneStatusResponse:
        return cls(
            id=scene.id,
            status=scene.status.value,
            pipeline_version=scene.pipeline_version,
            is_available=scene.is_available,
            is_terminal=scene.is_terminal,
            rejection_reason=scene.rejection_reason,
            version=scene.version,
            updated_at=scene.updated_at,
        )


class SceneMetadataResponse(BaseModel):
    """Canonical, provider-normalized scene metadata (spec §8)."""

    id: UUID
    provider: str
    provider_scene_id: str
    sensor_type: str
    acquired_at: datetime
    cloud_cover_pct: float | None
    sun_azimuth_deg: float | None
    sun_elevation_deg: float | None
    off_nadir_deg: float | None
    bands: list[BandSchema] | None
    crs_epsg: int | None
    quality_score: float | None
    checksum_sha256: str | None
    bounding_box: BoundingBoxSchema

    @classmethod
    def from_domain(cls, scene: Scene) -> SceneMetadataResponse:
        acq = scene.acquisition
        bands: list[BandSchema] | None = None
        if scene.bands is not None:
            bands = [
                BandSchema(
                    name=b.name,
                    index=b.index,
                    common_name=b.common_name,
                    wavelength_nm=b.wavelength_nm,
                    gsd_m=b.resolution.gsd_m if b.resolution is not None else None,
                )
                for b in scene.bands.bands
            ]
        return cls(
            id=scene.id,
            provider=scene.provider_scene_id.provider,
            provider_scene_id=str(scene.provider_scene_id),
            sensor_type=acq.sensor_type.value,
            acquired_at=acq.acquired_at,
            cloud_cover_pct=acq.cloud_cover.value if acq.cloud_cover is not None else None,
            sun_azimuth_deg=acq.sun_azimuth_deg,
            sun_elevation_deg=acq.sun_elevation_deg,
            off_nadir_deg=acq.off_nadir_deg,
            bands=bands,
            crs_epsg=scene.crs.epsg if scene.crs is not None else None,
            quality_score=scene.quality.value if scene.quality is not None else None,
            checksum_sha256=scene.checksum_sha256,
            bounding_box=BoundingBoxSchema.from_domain(scene.bounding_box),
        )


class AoiSummary(BaseModel):
    id: UUID
    name: str
    status: str
    priority: str
    revisit_cadence_days: int | None
    bounding_box: BoundingBoxSchema

    @classmethod
    def from_domain(cls, aoi: AreaOfInterest) -> AoiSummary:
        return cls(
            id=aoi.id,
            name=aoi.name,
            status=aoi.status.value,
            priority=aoi.priority.value,
            revisit_cadence_days=aoi.revisit_cadence_days,
            bounding_box=BoundingBoxSchema.from_domain(aoi.bounding_box),
        )


class AoiDetail(AoiSummary):
    jurisdiction_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, aoi: AreaOfInterest) -> AoiDetail:
        summary = AoiSummary.from_domain(aoi)
        return cls(
            **summary.model_dump(),
            jurisdiction_id=aoi.jurisdiction_id,
            version=aoi.version,
            created_at=aoi.created_at,
            updated_at=aoi.updated_at,
        )


class TimelineResponse(BaseModel):
    """Imagery history over an area, newest first (spec §10)."""

    area: BoundingBoxSchema
    count: int
    scenes: list[SceneSummary]


class TileMetadataResponse(BaseModel):
    """Metadata for one stored tile (the tile_index row projection)."""

    scene_id: UUID
    z: int
    x: int
    y: int
    tile_matrix_set: str
    pipeline_version: str
    storage_key: str
    etag: str
    size_bytes: int
    content_type: str
