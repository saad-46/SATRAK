"""Aggregate <-> record mappers (Epic 3 Story 8).

Bidirectional, lossless mapping between the domain aggregates and their persistence
records. ``*_from_record`` reconstitutes an aggregate *as persisted* — it never records
events (reconstitution is not a domain occurrence) and preserves the full audit envelope,
including the optimistic-concurrency version.
"""

from __future__ import annotations

from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SceneStatus, SensorType
from app.contexts.earth_observation.domain.value_objects.acquisition import AcquisitionMetadata
from app.contexts.earth_observation.domain.value_objects.band import Band, BandSet
from app.contexts.earth_observation.domain.value_objects.crs import CrsRef
from app.contexts.earth_observation.domain.value_objects.quality import (
    CloudCoverPercentage,
    QualityScore,
)
from app.contexts.earth_observation.domain.value_objects.resolution import Resolution
from app.contexts.earth_observation.domain.value_objects.scene_id import ProviderSceneId
from app.contexts.earth_observation.infrastructure.persistence.records import (
    AoiRecord,
    AuditFields,
    BandRecord,
    BoundingBoxRecord,
    SceneRecord,
)
from app.shared.domain.enums import EntityStatus, Priority
from app.shared.value_objects.geo import BoundingBox


def _audit_of(entity: Scene | AreaOfInterest) -> AuditFields:
    return AuditFields(
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        created_by=entity.created_by,
        updated_by=entity.updated_by,
        version=entity.version,
        is_deleted=entity.is_deleted,
        deleted_at=entity.deleted_at,
    )


def _bbox_to_record(box: BoundingBox) -> BoundingBoxRecord:
    return BoundingBoxRecord(
        min_longitude=box.min_longitude,
        min_latitude=box.min_latitude,
        max_longitude=box.max_longitude,
        max_latitude=box.max_latitude,
        srid=box.srid,
    )


def _bbox_from_record(record: BoundingBoxRecord) -> BoundingBox:
    return BoundingBox(
        min_longitude=record.min_longitude,
        min_latitude=record.min_latitude,
        max_longitude=record.max_longitude,
        max_latitude=record.max_latitude,
        srid=record.srid,
    )


def _bands_to_records(bands: BandSet | None) -> tuple[BandRecord, ...] | None:
    if bands is None:
        return None
    return tuple(
        BandRecord(
            name=b.name,
            index=b.index,
            common_name=b.common_name,
            wavelength_nm=b.wavelength_nm,
            gsd_m=b.resolution.gsd_m if b.resolution is not None else None,
        )
        for b in bands.bands
    )


def _bands_from_records(records: tuple[BandRecord, ...] | None) -> BandSet | None:
    if records is None:
        return None
    return BandSet(
        bands=tuple(
            Band(
                name=r.name,
                index=r.index,
                common_name=r.common_name,
                wavelength_nm=r.wavelength_nm,
                resolution=Resolution(gsd_m=r.gsd_m) if r.gsd_m is not None else None,
            )
            for r in records
        )
    )


# --- Scene ---------------------------------------------------------------------
def scene_to_record(scene: Scene) -> SceneRecord:
    acq = scene.acquisition
    return SceneRecord(
        id=scene.id,
        provider=scene.provider_scene_id.provider,
        provider_native_id=scene.provider_scene_id.native_id,
        status=scene.status.value,
        sensor_type=acq.sensor_type.value,
        acquired_at=acq.acquired_at,
        bounding_box=_bbox_to_record(scene.bounding_box),
        audit=_audit_of(scene),
        cloud_cover_pct=acq.cloud_cover.value if acq.cloud_cover is not None else None,
        sun_azimuth_deg=acq.sun_azimuth_deg,
        sun_elevation_deg=acq.sun_elevation_deg,
        off_nadir_deg=acq.off_nadir_deg,
        bands=_bands_to_records(scene.bands),
        crs_epsg=scene.crs.epsg if scene.crs is not None else None,
        quality_score=scene.quality.value if scene.quality is not None else None,
        checksum_sha256=scene.checksum_sha256,
        pipeline_version=scene.pipeline_version,
        rejection_reason=scene.rejection_reason,
        aoi_ids=tuple(sorted(scene.aoi_ids, key=str)),
    )


def scene_from_record(record: SceneRecord) -> Scene:
    audit = record.audit
    sensor_type = SensorType(record.sensor_type)
    return Scene(
        id=record.id,
        provider_scene_id=ProviderSceneId(
            provider=record.provider, native_id=record.provider_native_id
        ),
        bounding_box=_bbox_from_record(record.bounding_box),
        acquisition=AcquisitionMetadata(
            acquired_at=record.acquired_at,
            sensor_type=sensor_type,
            cloud_cover=(
                CloudCoverPercentage(value=record.cloud_cover_pct)
                if record.cloud_cover_pct is not None
                else None
            ),
            sun_azimuth_deg=record.sun_azimuth_deg,
            sun_elevation_deg=record.sun_elevation_deg,
            off_nadir_deg=record.off_nadir_deg,
        ),
        status=SceneStatus(record.status),
        bands=_bands_from_records(record.bands),
        crs=CrsRef(epsg=record.crs_epsg) if record.crs_epsg is not None else None,
        quality=(
            QualityScore(value=record.quality_score) if record.quality_score is not None else None
        ),
        checksum_sha256=record.checksum_sha256,
        pipeline_version=record.pipeline_version,
        rejection_reason=record.rejection_reason,
        aoi_ids=set(record.aoi_ids),
        created_at=audit.created_at,
        updated_at=audit.updated_at,
        created_by=audit.created_by,
        updated_by=audit.updated_by,
        version=audit.version,
        is_deleted=audit.is_deleted,
        deleted_at=audit.deleted_at,
    )


# --- AreaOfInterest --------------------------------------------------------------
def aoi_to_record(aoi: AreaOfInterest) -> AoiRecord:
    return AoiRecord(
        id=aoi.id,
        name=aoi.name,
        status=aoi.status.value,
        priority=aoi.priority.value,
        bounding_box=_bbox_to_record(aoi.bounding_box),
        audit=_audit_of(aoi),
        jurisdiction_id=aoi.jurisdiction_id,
        revisit_cadence_days=aoi.revisit_cadence_days,
    )


def aoi_from_record(record: AoiRecord) -> AreaOfInterest:
    audit = record.audit
    return AreaOfInterest(
        id=record.id,
        name=record.name,
        bounding_box=_bbox_from_record(record.bounding_box),
        status=EntityStatus(record.status),
        priority=Priority(record.priority),
        jurisdiction_id=record.jurisdiction_id,
        revisit_cadence_days=record.revisit_cadence_days,
        created_at=audit.created_at,
        updated_at=audit.updated_at,
        created_by=audit.created_by,
        updated_by=audit.updated_by,
        version=audit.version,
        is_deleted=audit.is_deleted,
        deleted_at=audit.deleted_at,
    )
