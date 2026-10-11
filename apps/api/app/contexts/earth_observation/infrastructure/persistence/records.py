"""Persistence reference records (Epic 3 Story 8).

Persistence-agnostic snapshots of the EO aggregates: flat, immutable rows of primitives +
UUIDs/datetimes that any storage technology (SQLAlchemy in Story 8's sequel, in-memory,
fixtures) can serialize without importing domain machinery. **No ORM, no repositories** —
these are the mapping contracts between aggregates and whatever persists them.

``SceneAssetRecord`` is the storage-reference model (spec §7/§13): pixels live in object
storage, so persistence tracks *references* per tier — never blobs (ADR-0006).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.contexts.earth_observation.domain.enums import AssetTier
from app.shared.domain.errors import ValueValidationError


@dataclass(frozen=True)
class AuditFields:
    """The shared audit envelope every aggregate row carries (ADR-0002)."""

    created_at: datetime
    updated_at: datetime
    created_by: UUID | None
    updated_by: UUID | None
    version: int
    is_deleted: bool
    deleted_at: datetime | None


@dataclass(frozen=True)
class BandRecord:
    """Flat band descriptor (mirrors the ``Band`` value object)."""

    name: str
    index: int
    common_name: str | None
    wavelength_nm: float | None
    gsd_m: float | None


@dataclass(frozen=True)
class BoundingBoxRecord:
    """Flat WGS84-or-projected extent (mirrors the shared ``BoundingBox``)."""

    min_longitude: float
    min_latitude: float
    max_longitude: float
    max_latitude: float
    srid: int


@dataclass(frozen=True)
class SceneRecord:
    """Identity + state snapshot of a ``Scene`` aggregate (spec §13 satellite_scenes)."""

    id: UUID
    provider: str
    provider_native_id: str
    status: str
    sensor_type: str
    acquired_at: datetime
    bounding_box: BoundingBoxRecord
    jurisdiction_id: UUID
    audit: AuditFields
    cloud_cover_pct: float | None = None
    sun_azimuth_deg: float | None = None
    sun_elevation_deg: float | None = None
    off_nadir_deg: float | None = None
    bands: tuple[BandRecord, ...] | None = None
    crs_epsg: int | None = None
    quality_score: float | None = None
    checksum_sha256: str | None = None
    pipeline_version: str | None = None
    rejection_reason: str | None = None
    aoi_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class AoiRecord:
    """Identity + state snapshot of an ``AreaOfInterest`` (spec §13 aoi_definitions)."""

    id: UUID
    name: str
    status: str
    priority: str
    bounding_box: BoundingBoxRecord
    jurisdiction_id: UUID
    audit: AuditFields
    revisit_cadence_days: int | None = None


@dataclass(frozen=True)
class SceneAssetRecord:
    """A storage reference for one asset of a scene (URI, never pixels — ADR-0006)."""

    scene_id: UUID
    tier: AssetTier
    storage_uri: str
    checksum_sha256: str | None = None
    pipeline_version: str | None = None
    size_bytes: int | None = None
    metadata: tuple[tuple[str, str], ...] = field(default=())

    def __post_init__(self) -> None:
        if not self.storage_uri.strip():
            raise ValueValidationError("storage_uri is required", field="storage_uri")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueValidationError("size_bytes must be >= 0", field="size_bytes")
