"""Story 8 — persistence reference records and lossless aggregate mappers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import AssetTier, SceneStatus, SensorType
from app.contexts.earth_observation.domain.value_objects import (
    AcquisitionMetadata,
    Band,
    BandSet,
    CloudCoverPercentage,
    CrsRef,
    ProviderSceneId,
    QualityScore,
    Resolution,
    TileMatrixSetRef,
)
from app.contexts.earth_observation.infrastructure.persistence import (
    SceneAssetRecord,
    aoi_from_record,
    aoi_to_record,
    scene_from_record,
    scene_to_record,
)
from app.shared.domain.enums import Priority
from app.shared.domain.errors import ValueValidationError
from app.shared.domain.identifiers import new_id
from app.shared.value_objects.geo import BoundingBox


def _scene() -> Scene:
    return Scene.create(
        provider_scene_id=ProviderSceneId(provider="sentinel-2", native_id="S2A_1"),
        bounding_box=BoundingBox(
            min_longitude=76.0, min_latitude=12.0, max_longitude=78.0, max_latitude=14.0
        ),
        acquisition=AcquisitionMetadata(
            acquired_at=datetime(2024, 6, 1, 5, 32, tzinfo=UTC),
            sensor_type=SensorType.OPTICAL,
            cloud_cover=CloudCoverPercentage(value=7.5),
            sun_azimuth_deg=121.4,
        ),
        bands=BandSet(
            bands=(
                Band(
                    name="B04",
                    index=3,
                    common_name="red",
                    wavelength_nm=665.0,
                    resolution=Resolution(gsd_m=10.0),
                ),
                Band(name="B08", index=7, wavelength_nm=842.0),
            )
        ),
    )


def _assert_scene_equal(a: Scene, b: Scene) -> None:
    assert a.id == b.id
    assert a.provider_scene_id == b.provider_scene_id
    assert a.status == b.status
    assert a.acquisition == b.acquisition
    assert a.bounding_box == b.bounding_box
    assert a.bands == b.bands
    assert a.crs == b.crs
    assert a.quality == b.quality
    assert a.checksum_sha256 == b.checksum_sha256
    assert a.pipeline_version == b.pipeline_version
    assert a.rejection_reason == b.rejection_reason
    assert a.aoi_ids == b.aoi_ids
    assert a.version == b.version
    assert a.created_at == b.created_at
    assert a.updated_at == b.updated_at
    assert a.is_deleted == b.is_deleted


def test_scene_round_trip_available_state() -> None:
    scene = _scene()
    scene.mark_downloaded(checksum_sha256="a" * 64)
    scene.mark_validated()
    scene.register(crs=CrsRef(epsg=32643), quality=QualityScore(value=0.9))
    scene.start_preprocessing(pipeline_version="v1")
    scene.mark_processed()
    scene.mark_tiled(tile_matrix_set=TileMatrixSetRef.web_mercator_quad())
    scene.mark_available()
    scene.link_aoi(new_id())
    scene.pull_events()

    restored = scene_from_record(scene_to_record(scene))
    _assert_scene_equal(scene, restored)
    assert restored.status is SceneStatus.AVAILABLE


def test_scene_round_trip_rejected_state() -> None:
    scene = _scene()
    scene.reject(reason="corrupt archive")
    scene.pull_events()
    restored = scene_from_record(scene_to_record(scene))
    _assert_scene_equal(scene, restored)
    assert restored.rejection_reason == "corrupt archive"


def test_scene_round_trip_sar_without_optical_fields() -> None:
    scene = Scene.create(
        provider_scene_id=ProviderSceneId(provider="sentinel-1", native_id="S1A_1"),
        bounding_box=BoundingBox(
            min_longitude=0.0, min_latitude=0.0, max_longitude=1.0, max_latitude=1.0
        ),
        acquisition=AcquisitionMetadata(
            acquired_at=datetime(2024, 6, 1, tzinfo=UTC), sensor_type=SensorType.SAR
        ),
    )
    record = scene_to_record(scene)
    assert record.cloud_cover_pct is None
    _assert_scene_equal(scene, scene_from_record(record))


def test_reconstitution_records_no_events() -> None:
    scene = _scene()
    scene.pull_events()
    restored = scene_from_record(scene_to_record(scene))
    assert restored.has_pending_events is False


def test_aoi_round_trip() -> None:
    aoi = AreaOfInterest.create(
        name="Ward 12",
        bounding_box=BoundingBox(
            min_longitude=76.0, min_latitude=12.0, max_longitude=78.0, max_latitude=14.0
        ),
        priority=Priority.HIGH,
        jurisdiction_id=new_id(),
        revisit_cadence_days=7,
    )
    aoi.deactivate()
    aoi.pull_events()

    restored = aoi_from_record(aoi_to_record(aoi))
    assert restored.id == aoi.id
    assert restored.name == aoi.name
    assert restored.status == aoi.status
    assert restored.priority is Priority.HIGH
    assert restored.bounding_box == aoi.bounding_box
    assert restored.jurisdiction_id == aoi.jurisdiction_id
    assert restored.revisit_cadence_days == 7
    assert restored.version == aoi.version
    assert restored.has_pending_events is False


def test_scene_asset_record_validation() -> None:
    record = SceneAssetRecord(
        scene_id=new_id(),
        tier=AssetTier.PROCESSED,
        storage_uri="processed/sentinel-2/optical/2024/06/01/x/v1/surface.tif",
        pipeline_version="v1",
        size_bytes=1024,
    )
    assert record.tier is AssetTier.PROCESSED
    with pytest.raises(ValueValidationError):
        SceneAssetRecord(scene_id=new_id(), tier=AssetTier.RAW, storage_uri="  ")
    with pytest.raises(ValueValidationError):
        SceneAssetRecord(scene_id=new_id(), tier=AssetTier.RAW, storage_uri="raw/x", size_bytes=-1)
